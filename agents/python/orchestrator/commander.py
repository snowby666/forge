# -*- coding: utf-8 -*-
"""
Commander — Layer 0: Orchestrator
===================================
Master LangGraph state machine. Coordinates all 30 specialist agents.
PostgreSQL checkpointing for crash recovery. Temporal for durability.

Entry point: python agents/python/orchestrator/commander.py --hackathon-id <id>
Or triggered automatically by Hackathon Scout via Redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from config.redis_client import get_redis
from redis.asyncio import Redis

from config.electronhub import complete_json
from config.agents_config import ALL_AGENTS, HUMAN_CHECKPOINTS
from agents.python.intelligence.hackathon_scout import HackathonBrief
from agents.python.intelligence.analysis_agents import run_all_intelligence
from agents.python.infra.monitor_and_calendar import (
    schedule_hackathon_events, send_discord_alert,
)

logger = logging.getLogger(__name__)

N8N_BASE = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
FORGE_WEB_URL = os.environ.get("FORGE_WEB_URL", "https://sentinelhive.dev")


# ── LangGraph state ────────────────────────────────────────────────────────────

class HackathonState(TypedDict):
    hackathon_id: str
    brief: dict
    intel: dict                         # comp_report, judge_profile, sponsor_map
    concepts: dict                      # 3 ranked concepts
    selected_concept: dict
    project_plan: dict
    db_schema: dict
    api_contract: dict
    design_spec: dict
    preview_url: str
    repo_url: str
    submission_url: str
    phase: str                          # current phase
    checkpoint_approvals: dict[str, bool]
    agent_statuses: dict[str, str]      # agent_id → status
    agent_failures: dict[str, int]      # agent_id → failure count
    errors: list[str]
    started_at: str
    messages: Annotated[list, add_messages]






_INLINE_TASKS: set[asyncio.Task] = set()


async def _dispatch_agent(agent_id: str, hackathon_id: str, inp: dict, redis: Redis) -> Any:
    """Route an agent trigger to its actual implementation function."""
    logger.info(f"[forge:dispatch] → dispatching {agent_id} (hackathon={hackathon_id})")
    if agent_id == "strategy_director":
        from agents.python.strategy.strategy_director import generate_concepts
        logger.info(f"[forge:dispatch] strategy_director: calling generate_concepts()")
        brief = await generate_concepts(
            hackathon_brief=inp.get("brief", {}),
            comp_report=inp.get("comp_report", {}),
            judge_profile=inp.get("judge_profile", {}),
            sponsor_map=inp.get("sponsor_map", {}),
            hackathon_id=hackathon_id,
        )
        logger.info(
            f"[forge:dispatch] strategy_director: got {len(brief.concepts)} concepts, "
            f"recommended=#{brief.recommended_concept}"
        )
        await redis.set(f"hackathon:{hackathon_id}:concepts", brief.model_dump_json(), ex=604800)
        return brief

    elif agent_id == "pm":
        from agents.python.strategy.pm_and_architect import create_project_plan
        return await create_project_plan(
            hackathon_id=hackathon_id,
            brief=inp.get("brief", {}),
            selected_concept=inp.get("selected_concept", {}),
            judge_profile=inp.get("judge_profile", {}),
            sponsor_map=inp.get("sponsor_map", {}),
            redis=redis,
        )

    elif agent_id == "tech_architect":
        from agents.python.strategy.pm_and_architect import design_architecture
        db_schema, api_contract, dep_graph = await design_architecture(
            hackathon_id=hackathon_id,
            project_plan=inp.get("project_plan", {}),
            redis=redis,
        )
        return {"endpoints": len(api_contract.endpoints)}

    elif agent_id == "ui_ux_designer":
        from agents.python.build.ui_ux_designer import run_ui_ux_agent
        output_dir = f"/tmp/hackathon-{hackathon_id}"
        return await run_ui_ux_agent(
            hackathon_id=hackathon_id,
            project_plan=inp.get("project_plan", {}),
            judge_profile=inp.get("judge_profile", {}),
            hackathon_brief=inp.get("brief", {}),
            output_dir=output_dir,
        )

    elif agent_id == "frontend_engineer":
        from agents.python.build.frontend_and_backend import run_frontend_engineer
        return await run_frontend_engineer(
            hackathon_id=hackathon_id,
            project_plan=inp.get("project_plan", {}),
            design_spec=inp.get("design_spec", {}),
            design_tokens_content=inp.get("design_tokens_content", ""),
            component_specs=inp.get("component_specs", []),
            design_md_content=inp.get("design_md_content", ""),
            api_contract=inp.get("api_contract", {}),
        )

    elif agent_id == "backend_engineer":
        from agents.python.build.frontend_and_backend import run_backend_engineer
        return await run_backend_engineer(
            hackathon_id=hackathon_id,
            project_plan=inp.get("project_plan", {}),
            db_schema=inp.get("db_schema", {}),
            simplify=inp.get("simplify", False),
        )

    elif agent_id in ("integration_engineer", "test_engineer", "devops", "security", "code_reviewer", "performance"):
        from agents.python.build.build_verify_agents import AGENT_HANDLERS as BV_HANDLERS
        result = await BV_HANDLERS[agent_id](hackathon_id, inp)
        artifact_key = {
            "integration_engineer": "sponsor_integration_manifest",
            "test_engineer": "test_suite",
            "devops": "cicd_config",
            "security": "security_report",
            "code_reviewer": "code_review_report",
            "performance": "performance_report",
        }.get(agent_id, agent_id)
        output = result.model_dump() if hasattr(result, "model_dump") else result
        await redis.set(f"hackathon:{hackathon_id}:{artifact_key}", json.dumps(output), ex=604800)
        return result

    elif agent_id == "ux_auditor":
        from agents.python.verify.ux_auditor import run_ux_audit
        report = await run_ux_audit(
            hackathon_id=hackathon_id,
            preview_url=inp.get("preview_url", ""),
            design_spec=inp.get("design_spec", {}),
            design_md_path=inp.get("design_md_path", ""),
        )
        if not report.approved:
            await redis.publish("commander:audit_failed", json.dumps({
                "hackathon_id": hackathon_id,
                "score": report.overall_score,
                "blockers": report.blockers,
                "instructions": report.iteration_instructions,
            }))
        return report

    elif agent_id == "polish":
        from agents.python.polish.polish_agents import run_polish_agent
        return await run_polish_agent(
            hackathon_id=hackathon_id,
            preview_url=inp.get("preview_url", ""),
            ux_audit_report=inp.get("ux_audit_report", {}),
            frontend_repo_path=inp.get("frontend_repo_path", ""),
            output_dir=f"/tmp/hackathon-{hackathon_id}",
            redis=redis,
        )

    elif agent_id == "copy_writer":
        from agents.python.polish.polish_agents import run_copy_writer
        return await run_copy_writer(
            hackathon_id=hackathon_id,
            frontend_repo_path=inp.get("frontend_repo_path", ""),
            judge_profile=inp.get("judge_profile", {}),
            project_plan=inp.get("project_plan", {}),
            redis=redis,
        )

    elif agent_id == "data_seeder":
        from agents.python.polish.polish_agents import generate_seed_data
        return await generate_seed_data(
            hackathon_id=hackathon_id,
            project_plan=inp.get("project_plan", {}),
            api_contract=inp.get("api_contract", {}),
            redis=redis,
        )

    elif agent_id == "brand":
        from agents.python.polish.polish_agents import create_brand_kit
        return await create_brand_kit(
            hackathon_id=hackathon_id,
            design_spec=inp.get("design_spec", {}),
            project_plan=inp.get("project_plan", {}),
            output_dir=f"/tmp/hackathon-{hackathon_id}",
            redis=redis,
        )

    elif agent_id == "demo_producer":
        from agents.python.submission.submission_pipeline import run_demo_producer
        return await run_demo_producer(
            hackathon_id=hackathon_id,
            preview_url=inp.get("preview_url", ""),
            project_plan=inp.get("project_plan", {}),
            judge_profile=inp.get("judge_profile", {}),
            output_dir=f"/tmp/hackathon-{hackathon_id}",
        )

    elif agent_id == "pitch_writer":
        from agents.python.submission.submission_pipeline import run_pitch_writer
        return await run_pitch_writer(
            hackathon_id=hackathon_id,
            project_plan=inp.get("project_plan", {}),
            judge_profile=inp.get("judge_profile", {}),
            sponsor_manifest=inp.get("sponsor_manifest", {}),
            repo_url=inp.get("repo_url", ""),
            preview_url=inp.get("preview_url", ""),
            video_url=inp.get("video_url", ""),
            output_dir=f"/tmp/hackathon-{hackathon_id}",
        )

    elif agent_id == "submission":
        from agents.python.submission.submission_pipeline import run_submission_agent
        return await run_submission_agent(
            hackathon_id=hackathon_id,
            hackathon_url=inp.get("hackathon_url", ""),
            platform=inp.get("platform", "devpost"),
            project_plan=inp.get("project_plan", {}),
            description=inp.get("description", ""),
            video_url=inp.get("video_url", ""),
            preview_url=inp.get("preview_url", ""),
            repo_url=inp.get("repo_url", ""),
            sponsor_manifest=inp.get("sponsor_manifest", {}),
            output_dir=inp.get("output_dir", f"/tmp/hackathon-{hackathon_id}"),
        )

    elif agent_id == "outcome_tracker":
        from agents.python.infra.outcome_tracker import run_outcome_tracker
        return await run_outcome_tracker(hackathon_id)

    else:
        raise ValueError(f"[forge:worker] Unknown agent: {agent_id}")


async def _set_task_status(hackathon_id: str, agent_id: str, payload: dict) -> None:
    """Write task status to Redis with a fresh connection (avoids stale idle connections)."""
    r = get_redis()
    try:
        await r.set(f"task:{hackathon_id}:{agent_id}", json.dumps(payload), ex=604800)
    finally:
        await r.aclose()


async def _run_agent_inline(hackathon_id: str, agent_id: str, input_data: dict) -> None:
    """Execute an agent function in-process and store result in Redis."""
    import time as _t
    t0 = _t.monotonic()
    logger.info(f"[forge:worker] ▶ {agent_id} starting inline (hackathon={hackathon_id})")
    try:
        await _set_task_status(hackathon_id, agent_id, {"status": "in-progress"})

        redis = get_redis()
        try:
            result = await _dispatch_agent(agent_id, hackathon_id, input_data, redis)
        finally:
            await redis.aclose()

        elapsed = _t.monotonic() - t0
        output = result.model_dump() if hasattr(result, "model_dump") else (result or {})
        await _set_task_status(hackathon_id, agent_id, {"status": "done", "data": output})
        logger.info(f"[forge:worker] ✓ {agent_id} completed inline ({elapsed:.1f}s)")
    except Exception as e:
        elapsed = _t.monotonic() - t0
        logger.error(
            f"[forge:worker] ✗ {agent_id} failed after {elapsed:.1f}s: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        try:
            await _set_task_status(hackathon_id, agent_id, {"status": "failed", "error": str(e)})
        except Exception:
            logger.error(f"[forge:worker] Could not write failure status to Redis for {agent_id}")


async def trigger_agent(redis: Redis, hackathon_id: str, agent_id: str, input_data: dict) -> None:
    logger.info(f"[forge:commander]   → Triggering {agent_id}")
    await redis.set(f"task:{hackathon_id}:{agent_id}", json.dumps({"status": "pending"}), ex=604800)
    task = asyncio.create_task(_run_agent_inline(hackathon_id, agent_id, input_data))
    _INLINE_TASKS.add(task)
    task.add_done_callback(_INLINE_TASKS.discard)


async def wait_for_agent(redis: Redis, hackathon_id: str, agent_id: str, timeout_sec: int = 3600) -> dict | None:
    """Poll Redis until agent completes or times out."""
    logger.info(f"[forge:commander]   Waiting for {agent_id} (timeout: {timeout_sec}s)...")
    start = datetime.now(timezone.utc).timestamp()
    last_log = start
    while True:
        raw = await redis.get(f"task:{hackathon_id}:{agent_id}")
        if raw:
            task = json.loads(raw)
            if task["status"] == "done":
                elapsed = datetime.now(timezone.utc).timestamp() - start
                logger.info(f"[forge:commander]   ✓ {agent_id} done ({elapsed:.0f}s)")
                return task.get("data")
            if task["status"] == "failed":
                elapsed = datetime.now(timezone.utc).timestamp() - start
                logger.error(f"[forge:commander]   ✗ {agent_id} FAILED ({elapsed:.0f}s): {task.get('error', '?')}")
                return None
        elapsed = datetime.now(timezone.utc).timestamp() - start
        now = datetime.now(timezone.utc).timestamp()
        if now - last_log > 30:
            status = task["status"] if raw else "no-key"
            logger.info(
                f"[forge:commander]   ⟳ Still waiting for {agent_id}... "
                f"({elapsed:.0f}s elapsed, redis_status={status})"
            )
            last_log = now
        if elapsed > timeout_sec:
            logger.warning(f"[forge:commander]   ⏰ {agent_id} TIMED OUT after {timeout_sec}s")
            return None
        await asyncio.sleep(5)


async def wait_for_checkpoint(
    redis: Redis,
    hackathon_id: str,
    checkpoint_id: str,
    timeout_hours: int = 24,
) -> dict | None:
    """Poll Redis for human checkpoint approval."""
    key = f"checkpoint:{hackathon_id}:{checkpoint_id}"
    timeout_sec = timeout_hours * 3600
    start = datetime.now(timezone.utc).timestamp()

    await redis.set(key, "pending", ex=timeout_sec)

    logger.info(
        f"[forge:commander]   ⏸  Waiting for human: {checkpoint_id}\n"
        f"[forge:commander]      Approve via: forge approve {checkpoint_id.split('_')[0]} --id {hackathon_id}\n"
        f"[forge:commander]      Timeout: {timeout_hours}h (auto-proceeds on timeout)"
    )

    while True:
        raw = await redis.get(key)
        if raw and raw != "pending":
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = None
            if data and isinstance(data, dict) and data.get("approved"):
                logger.info(f"[forge:commander]   ✓ {checkpoint_id} APPROVED by human")
                return data
        elapsed = datetime.now(timezone.utc).timestamp() - start
        if elapsed > timeout_sec:
            logger.warning(f"[forge:commander]   ⏰ {checkpoint_id} timed out after {timeout_hours}h — auto-proceeding")
            return None
        await asyncio.sleep(30)


async def notify_checkpoint(hackathon_id: str, checkpoint_id: str, message: str) -> None:
    web_token = os.environ.get("FORGE_WEB_TOKEN", "")
    token_qs = f"?token={web_token}" if web_token else ""
    await send_discord_alert(
        f"**Hackathon Agent — Action Required** :dart:\n{message}\n\n"
        f"**Approve from any device:** {FORGE_WEB_URL}/approve/{hackathon_id}/{checkpoint_id}{token_qs}\n"
        f"**CLI:** `forge approve {checkpoint_id.replace('_approval','').replace('_review','')} --id {hackathon_id}`"
    )


# ── Graph nodes ────────────────────────────────────────────────────────────────

async def run_intelligence(state: HackathonState) -> dict:
    """Layer 1: Run all 4 intel agents in parallel."""
    logger.info(
        f"[forge:commander] ━━━ Phase 1: INTELLIGENCE ━━━\n"
        f"[forge:commander]   Running: Competitor Analyst, Judge Profiler, Sponsor Researcher (parallel)\n"
        f"[forge:commander]   Hackathon: {state['brief'].get('name')}"
    )
    import time as _time
    t0 = _time.monotonic()
    redis = get_redis()
    logger.info(f"[forge:commander]   Scheduling calendar events...")
    await schedule_hackathon_events(
        state["hackathon_id"], state["brief"].get("name", "Hackathon"),
        state["brief"].get("deadline", ""), ""
    )
    logger.info(f"[forge:commander]   Starting 4 intelligence agents in parallel...")
    intel = await run_all_intelligence(state["hackathon_id"], state["brief"])
    elapsed = _time.monotonic() - t0
    logger.info(
        f"[forge:commander]   Intelligence complete in {elapsed:.0f}s\n"
        f"[forge:commander]   CompReport: {'yes' if intel.get('comp_report') else 'no'}\n"
        f"[forge:commander]   JudgeProfile: {'yes' if intel.get('judge_profile') else 'no'}\n"
        f"[forge:commander]   SponsorMap: {'yes' if intel.get('sponsor_map') else 'no'}"
    )
    await redis.aclose()
    return {"intel": intel, "phase": "strategy"}


async def generate_concepts(state: HackathonState) -> dict:
    """Trigger Strategy Director, wait for concepts, notify human."""
    logger.info(f"[forge:commander] ━━━ Phase 1b: CONCEPT GENERATION ━━━")
    redis = get_redis()

    await trigger_agent(redis, state["hackathon_id"], "strategy_director", {
        "brief": state["brief"],
        **state["intel"],
    })
    data = await wait_for_agent(redis, state["hackathon_id"], "strategy_director", timeout_sec=300)

    if not data:
        await redis.aclose()
        return {"errors": [*state["errors"], "strategy_director failed"]}

    concepts = data
    best = concepts.get("concepts", [{}])[0]

    await notify_checkpoint(
        state["hackathon_id"], "concept_approval",
        f"3 concepts ready for *{state['brief'].get('name')}*\n"
        + "\n".join(
            f"{i+1}. *{c.get('project_name')}* (score: {c.get('total_score')}) — {c.get('tagline')}"
            for i, c in enumerate(concepts.get("concepts", [])[:3])
        ) + f"\n\nRecommended: #{concepts.get('recommended_concept', 1)}"
    )
    await redis.aclose()
    return {"concepts": concepts}


async def wait_concept_approval(state: HackathonState) -> dict:
    """Wait for human to pick a concept."""
    redis = get_redis()
    cfg = HUMAN_CHECKPOINTS["concept_approval"]
    approval = await wait_for_checkpoint(redis, state["hackathon_id"], "concept_approval", cfg["timeout_hours"])

    if not approval:
        # Auto-select recommended concept on timeout
        recommended_idx = state["concepts"].get("recommended_concept", 1) - 1
        concept_list = state["concepts"].get("concepts", [{}])
        selected = concept_list[min(recommended_idx, len(concept_list) - 1)]
        logger.warning(f"[forge:commander] Concept approval timed out — auto-selecting #{recommended_idx + 1}")
    else:
        concept_idx = approval.get("concept_index", 0)
        selected = state["concepts"].get("concepts", [{}])[concept_idx]

    await redis.aclose()
    return {
        "selected_concept": selected,
        "checkpoint_approvals": {**state["checkpoint_approvals"], "concept_approval": True},
        "phase": "planning",
    }


async def run_planning(state: HackathonState) -> dict:
    """Run PM + Tech Architect in parallel."""
    logger.info(
        f"[forge:commander] ━━━ Phase 2: PLANNING ━━━\n"
        f"[forge:commander]   Concept: {state['selected_concept'].get('project_name', '?')}\n"
        f"[forge:commander]   Running: PM + Tech Architect (parallel)"
    )
    redis = get_redis()

    # Trigger PM and Architect in parallel
    await asyncio.gather(
        trigger_agent(redis, state["hackathon_id"], "pm", {
            "brief": state["brief"],
            "selected_concept": state["selected_concept"],
            "judge_profile": state["intel"].get("judge_profile", {}),
            "sponsor_map": state["intel"].get("sponsor_map", {}),
        }),
        trigger_agent(redis, state["hackathon_id"], "tech_architect", {
            "selected_concept": state["selected_concept"],
        }),
    )

    pm_data, arch_data = await asyncio.gather(
        wait_for_agent(redis, state["hackathon_id"], "pm", timeout_sec=300),
        wait_for_agent(redis, state["hackathon_id"], "tech_architect", timeout_sec=300),
    )

    if not pm_data:
        await redis.aclose()
        return {"errors": [*state["errors"], "PM agent failed"]}

    # Load api_contract from Redis (Architect publishes it immediately)
    api_contract_raw = await redis.get(f"hackathon:{state['hackathon_id']}:api_contract")
    api_contract = json.loads(api_contract_raw) if api_contract_raw else {}
    db_schema_raw = await redis.get(f"hackathon:{state['hackathon_id']}:db_schema")
    db_schema = json.loads(db_schema_raw) if db_schema_raw else {}

    await redis.aclose()
    return {
        "project_plan": pm_data,
        "api_contract": api_contract,
        "db_schema": db_schema,
        "phase": "design",
    }


async def run_design(state: HackathonState) -> dict:
    """Trigger UI/UX Designer, wait, notify human for design approval."""
    logger.info(
        f"[forge:commander] ━━━ Phase 2b: DESIGN ━━━\n"
        f"[forge:commander]   Running: UI/UX Designer\n"
        f"[forge:commander]   Project: {state['project_plan'].get('project_name', '?')}"
    )
    redis = get_redis()

    await trigger_agent(redis, state["hackathon_id"], "ui_ux_designer", {
        "project_plan": state["project_plan"],
        "brief": state["brief"],
        "judge_profile": state["intel"].get("judge_profile", {}),
    })

    design_data = await wait_for_agent(redis, state["hackathon_id"], "ui_ux_designer", timeout_sec=900)

    if not design_data:
        await redis.aclose()
        return {"errors": [*state["errors"], "UI/UX Designer failed"]}

    await notify_checkpoint(
        state["hackathon_id"], "design_approval",
        f"Design complete for *{state['project_plan'].get('project_name')}*\n"
        f"• Personality: {design_data.get('personality')}\n"
        f"• Screens: {design_data.get('screen_count')}\n"
        f"• Components: {design_data.get('component_count')} ({design_data.get('demo_critical_components')} demo-critical)\n"
        f"• Self-critique score: {design_data.get('self_critique', {}).get('overall_score', '?')}/10\n\n"
        f"Review DESIGN.md and Figma before approving.\n"
        f"Run `forge plan --id {state['hackathon_id']}` to see the full build plan."
    )
    await redis.aclose()
    return {"design_spec": design_data}


async def generate_build_plan(state: HackathonState) -> dict:
    """
    Feature 6: Generate a structured build plan before design approval.
    Adapted from Claude Code's /ultraplan command.

    Shows the human: exactly what each agent will build, in what order,
    with dependency relationships and risk items. Injected into the
    design approval Discord notification so humans approve with full context.
    """
    from config.electronhub import complete_json as _cj
    from pydantic import BaseModel as _BM

    class BuildTask(_BM):
        agent: str
        description: str
        depends_on: list[str]
        estimated_hours: float
        risk: str  # "low" | "medium" | "high"

    class BuildPlan(_BM):
        tasks: list[BuildTask]
        critical_path: list[str]   # agent IDs on the critical path
        total_estimated_hours: float
        biggest_risk: str
        demo_path_components: list[str]  # components judges will see in 90s

    try:
        plan = await _cj(
            task="create-sprint-plan",
            response_model=BuildPlan,
            messages=[{
                "role": "user",
                "content": f"""Generate the build plan for this hackathon project.

Project: {state['project_plan'].get('project_name')}
Core features: {json.dumps(state['project_plan'].get('core_features', [])[:2], indent=2)}
API endpoints: {len(state.get('api_contract', {}).get('endpoints', []))}
DB tables: {len(state.get('db_schema', {}).get('tables', []))}
Screens designed: {state.get('design_spec', {}).get('screen_count', '?')}
Demo-critical components: {state.get('design_spec', {}).get('demo_critical_components', '?')}

Build agents available:
- frontend_engineer: Next.js 14, React, Tailwind, shadcn/ui
- backend_engineer: FastAPI, SQLAlchemy, PostgreSQL
- integration_engineer: Sponsor API modules
- test_engineer: Playwright e2e + pytest
- devops: GitHub Actions CI/CD
- security: Secret scan + npm audit

Output a realistic plan. Critical path = the sequence that determines total build time.
demo_path_components = the 3-5 UI components judges will see in the demo.""",
            }],
            temperature=0.2,
        )
        plan_dict = plan.model_dump()
        # Store for forge plan command to display
        redis = get_redis()
        await redis.set(
            f"hackathon:{state['hackathon_id']}:build_plan",
            json.dumps(plan_dict),
            ex=604800,
        )
        await redis.aclose()
        logger.info(
            f"[forge:commander] Build plan generated: {len(plan.tasks)} tasks, "
            f"{plan.total_estimated_hours:.1f}h estimated, risk: {plan.biggest_risk[:50]}"
        )
        return {"build_plan": plan_dict}
    except Exception as e:
        logger.warning(f"[forge:commander] Build plan generation failed (non-blocking): {e}")
        return {}


async def wait_design_approval(state: HackathonState) -> dict:
    """Wait for human design approval."""
    redis = get_redis()
    cfg = HUMAN_CHECKPOINTS["design_approval"]
    approval = await wait_for_checkpoint(redis, state["hackathon_id"], "design_approval", cfg["timeout_hours"])

    if not approval:
        logger.warning("[forge:commander] Design approval timed out — proceeding with current design")

    await redis.aclose()
    return {
        "checkpoint_approvals": {**state["checkpoint_approvals"], "design_approval": True},
        "phase": "building",
    }


async def run_build(state: HackathonState) -> dict:
    """
    Trigger all build agents in dependency-correct order.
    Uses forge_tools.get_runnable_now() — adapted from Claude Code's
    isConcurrencySafe() concurrency scheduling pattern.
    """
    logger.info(
        f"[forge:commander] ━━━ Phase 3: BUILD ━━━\n"
        f"[forge:commander]   Running: Frontend, Backend, Integration, Test, DevOps, Security\n"
        f"[forge:commander]   Dependency-ordered scheduling via get_runnable_now()"
    )
    redis = get_redis()

    design = state.get("design_spec", {})

    # Full input data per agent
    agent_inputs: dict[str, dict] = {
        "frontend_engineer": {
            "project_plan": state["project_plan"],
            "design_spec": design,
            "design_tokens_content": design.get("tokens", {}).get("typescript_content", ""),
            "component_specs": design.get("design_spec", {}).get("components", []),
            "design_md_content": "",
            "api_contract": state.get("api_contract"),
        },
        "backend_engineer": {
            "project_plan": state["project_plan"],
            "db_schema": state.get("db_schema", {}),
        },
        "integration_engineer": {
            "project_plan": state["project_plan"],
            "sponsor_map": state["intel"].get("sponsor_map", {}),
            "api_contract": state.get("api_contract"),
        },
        "test_engineer": {
            "project_plan": state["project_plan"],
            "api_contract": state.get("api_contract"),
        },
        "devops": {
            "project_plan": state["project_plan"],
            "api_contract": state.get("api_contract"),
        },
        "security": {},
    }

    build_agents = list(agent_inputs.keys())
    completed: set[str] = set()
    in_progress: set[str] = set()
    frontend_data: dict | None = None

    from config.forge_tools import get_runnable_now

    # Dependency-aware scheduling loop
    while len(completed) < len(build_agents):
        runnable = get_runnable_now(completed, in_progress, build_agents)
        if not runnable and not in_progress:
            logger.error("[forge:commander] Build deadlock — agents stuck")
            break

        # Trigger all newly runnable agents
        for agent_id in runnable:
            in_progress.add(agent_id)
            await trigger_agent(redis, state["hackathon_id"], agent_id, agent_inputs[agent_id])
            logger.info(f"[forge:commander] Triggered (dependency-ordered): {agent_id}")

        # Wait for any in-progress agent to complete (poll)
        await asyncio.sleep(5)
        newly_done: set[str] = set()
        for agent_id in list(in_progress):
            raw = await redis.get(f"task:{state['hackathon_id']}:{agent_id}")
            if raw:
                task = json.loads(raw)
                if task["status"] == "done":
                    newly_done.add(agent_id)
                    if agent_id == "frontend_engineer":
                        frontend_data = task.get("data")
                elif task["status"] == "failed":
                    newly_done.add(agent_id)
                    agent_failures = state.get("agent_failures", {})
                    agent_failures[agent_id] = agent_failures.get(agent_id, 0) + 1
                    if agent_failures[agent_id] < 2:
                        logger.warning(f"[forge:commander] {agent_id} failed (attempt {agent_failures[agent_id]}), retrying with simplify")
                        await trigger_agent(redis, state["hackathon_id"], agent_id, {
                            **agent_inputs[agent_id], "simplify": True,
                        })
                        in_progress.add(agent_id)
                    else:
                        logger.error(f"[forge:commander] {agent_id} failed {agent_failures[agent_id]} times, skipping")

        in_progress -= newly_done
        completed   |= newly_done

    if not frontend_data:
        # Retry frontend with simplify=True
        await trigger_agent(redis, state["hackathon_id"], "frontend_engineer", {
            **agent_inputs["frontend_engineer"], "simplify": True,
        })
        frontend_data = await wait_for_agent(
            redis, state["hackathon_id"], "frontend_engineer", timeout_sec=1800
        )
        if not frontend_data:
            await redis.aclose()
            return {"errors": [*state["errors"], "Frontend build failed after simplify attempt"]}

    preview_url = frontend_data.get("preview_url", "")
    repo_url    = frontend_data.get("repo_url", "")

    await redis.aclose()
    return {"preview_url": preview_url, "repo_url": repo_url, "phase": "verifying"}


async def run_verification(state: HackathonState) -> dict:
    """Run Code Reviewer + UX Auditor + Performance in parallel."""
    logger.info(
        f"[forge:commander] ━━━ Phase 4: VERIFICATION ━━━\n"
        f"[forge:commander]   Running: Code Reviewer, UX Auditor [veto], Performance Agent\n"
        f"[forge:commander]   Preview: {state.get('preview_url', '?')}"
    )
    redis = get_redis()
    design = state.get("design_spec", {})

    for agent_id, input_data in [
        ("code_reviewer", {"preview_url": state["preview_url"]}),
        ("ux_auditor", {
            "preview_url": state["preview_url"],
            "design_spec": design.get("design_spec", {}),
            "design_md_path": design.get("design_md_path", ""),
        }),
        ("performance", {"preview_url": state["preview_url"]}),
    ]:
        await trigger_agent(redis, state["hackathon_id"], agent_id, input_data)

    # UX Auditor is the gating agent
    ux_data = await wait_for_agent(redis, state["hackathon_id"], "ux_auditor", timeout_sec=600)

    max_ux_retries = 2
    ux_attempt = 0
    while ux_data and not ux_data.get("approved", False) and ux_attempt < max_ux_retries:
        ux_attempt += 1
        score = ux_data.get("overall_score", 0)
        blockers = ux_data.get("blockers", [])
        logger.warning(
            f"[forge:commander] UX Auditor BLOCKED (attempt {ux_attempt}/{max_ux_retries}). "
            f"Score: {score}, Blockers: {blockers}"
        )
        await trigger_agent(redis, state["hackathon_id"], "polish", {
            "preview_url": state["preview_url"],
            "ux_audit_report": ux_data,
            "frontend_repo_path": "",
        })
        await wait_for_agent(redis, state["hackathon_id"], "polish", timeout_sec=600)
        await trigger_agent(redis, state["hackathon_id"], "ux_auditor", {
            "preview_url": state["preview_url"],
            "design_spec": design.get("design_spec", {}),
            "design_md_path": design.get("design_md_path", ""),
        })
        ux_data = await wait_for_agent(redis, state["hackathon_id"], "ux_auditor", timeout_sec=600)

    if ux_data and not ux_data.get("approved", False):
        logger.error(
            f"[forge:commander] UX Auditor still blocked after {max_ux_retries} retries — escalating to human"
        )
        await redis.publish("commander:audit_failed", json.dumps({
            "hackathon_id": state["hackathon_id"],
            "score": ux_data.get("overall_score", 0),
            "blockers": ux_data.get("blockers", []),
        }))
        await send_discord_alert(
            f"**UX Audit Escalation** :warning:\n"
            f"Hackathon: {state.get('project_plan', {}).get('project_name', state['hackathon_id'])}\n"
            f"Score: {ux_data.get('overall_score', '?')}/10 after {max_ux_retries} fix attempts\n"
            f"Blockers: {', '.join(ux_data.get('blockers', []))}\n"
            f"Preview: {state['preview_url']}\n\n"
            f"Proceeding to quality review — manual intervention recommended."
        )

    await notify_checkpoint(
        state["hackathon_id"], "quality_review",
        f"Build complete for *{state['project_plan'].get('project_name')}*\n"
        f"• Preview: {state['preview_url']}\n"
        f"• UX Audit score: {ux_data.get('overall_score', '?') if ux_data else '?'}/10\n"
        f"• Status: {'✅ Approved' if ux_data and ux_data.get('approved') else '⚠️ Issues found'}\n\n"
        f"Check it on mobile (375px). Submission is BLOCKED until you approve."
    )
    await redis.aclose()
    return {"phase": "polishing"}


async def wait_quality_review(state: HackathonState) -> dict:
    redis = get_redis()
    cfg = HUMAN_CHECKPOINTS["quality_review"]
    approval = await wait_for_checkpoint(redis, state["hackathon_id"], "quality_review", cfg["timeout_hours"])
    await redis.aclose()
    return {"checkpoint_approvals": {**state["checkpoint_approvals"], "quality_review": True}, "phase": "polishing"}


async def run_polish(state: HackathonState) -> dict:
    """Run all 4 polish agents in parallel."""
    logger.info(
        f"[forge:commander] ━━━ Phase 5: POLISH ━━━\n"
        f"[forge:commander]   Running: Polish Agent, Copy Writer, Data Seeder, Brand Agent (parallel)"
    )
    redis = get_redis()

    design = state.get("design_spec", {})
    ux_audit_raw = await redis.get(f"task:{state['hackathon_id']}:ux_auditor")
    ux_audit = json.loads(ux_audit_raw).get("data", {}) if ux_audit_raw else {}
    api_contract_raw = await redis.get(f"hackathon:{state['hackathon_id']}:api_contract")
    api_contract = json.loads(api_contract_raw) if api_contract_raw else {}

    for agent_id, input_data in [
        ("polish", {"preview_url": state["preview_url"], "ux_audit_report": ux_audit}),
        ("copy_writer", {"judge_profile": state["intel"].get("judge_profile", {}), "project_plan": state["project_plan"]}),
        ("data_seeder", {"project_plan": state["project_plan"], "api_contract": api_contract}),
        ("brand", {"design_spec": design.get("design_spec", {}), "project_plan": state["project_plan"]}),
    ]:
        await trigger_agent(redis, state["hackathon_id"], agent_id, input_data)

    # Wait for polish to complete (parallel)
    await asyncio.gather(
        wait_for_agent(redis, state["hackathon_id"], "polish", timeout_sec=600),
        wait_for_agent(redis, state["hackathon_id"], "copy_writer", timeout_sec=300),
        wait_for_agent(redis, state["hackathon_id"], "data_seeder", timeout_sec=300),
        wait_for_agent(redis, state["hackathon_id"], "brand", timeout_sec=300),
    )
    await redis.aclose()
    return {"phase": "submitting"}


async def run_submission(state: HackathonState) -> dict:
    """Run demo producer + pitch writer in parallel, then submit."""
    logger.info(
        f"[forge:commander] ━━━ Phase 6: SUBMISSION ━━━\n"
        f"[forge:commander]   Running: Demo Producer + Pitch Writer (parallel), then Submission Agent\n"
        f"[forge:commander]   Preview: {state.get('preview_url', '?')}"
    )
    redis = get_redis()

    sponsor_manifest_raw = await redis.get(f"hackathon:{state['hackathon_id']}:sponsor_map")
    sponsor_manifest = json.loads(sponsor_manifest_raw) if sponsor_manifest_raw else {}
    output_dir = f"/tmp/hackathon-{state['hackathon_id']}"

    for agent_id, input_data in [
        ("demo_producer", {
            "preview_url": state["preview_url"],
            "project_plan": state["project_plan"],
            "judge_profile": state["intel"].get("judge_profile", {}),
            "output_dir": output_dir,
        }),
        ("pitch_writer", {
            "project_plan": state["project_plan"],
            "judge_profile": state["intel"].get("judge_profile", {}),
            "sponsor_manifest": sponsor_manifest,
            "repo_url": state.get("repo_url", ""),
            "preview_url": state["preview_url"],
            "output_dir": output_dir,
        }),
    ]:
        await trigger_agent(redis, state["hackathon_id"], agent_id, input_data)

    demo_data, pitch_data = await asyncio.gather(
        wait_for_agent(redis, state["hackathon_id"], "demo_producer", timeout_sec=1200),
        wait_for_agent(redis, state["hackathon_id"], "pitch_writer", timeout_sec=600),
    )

    video_url = demo_data.get("video_url", "") if demo_data else ""

    await notify_checkpoint(
        state["hackathon_id"], "submission_approval",
        f"**Ready to submit!** — {state['project_plan'].get('project_name')}\n"
        f"• Preview: {state['preview_url']}\n"
        f"• Video: {video_url or 'generating...'}\n"
        f"• Submission description preview:\n"
        + (pitch_data.get("description", "")[:150] if pitch_data else "generating...") + "...\n\n"
        f"⚠️ Submitting to: {state['brief'].get('url')}"
    )

    cfg = HUMAN_CHECKPOINTS["submission_approval"]
    approval = await wait_for_checkpoint(redis, state["hackathon_id"], "submission_approval", cfg["timeout_hours"])

    submission_url = ""
    if approval:
        # Final submission
        await trigger_agent(redis, state["hackathon_id"], "submission", {
            "hackathon_url": state["brief"].get("url"),
            "platform": state["brief"].get("platform", "devpost"),
            "project_plan": state["project_plan"],
            "description": pitch_data.get("description", "") if pitch_data else "",
            "video_url": video_url,
            "preview_url": state["preview_url"],
            "repo_url": state.get("repo_url", ""),
            "sponsor_manifest": sponsor_manifest,
            "output_dir": output_dir,
        })
        sub_data = await wait_for_agent(redis, state["hackathon_id"], "submission", timeout_sec=600)
        submission_url = sub_data.get("submission_url", "") if sub_data else ""

    await redis.aclose()
    return {
        "submission_url": submission_url,
        "phase": "done",
        "hackathon_id": state["hackathon_id"],
    }


async def schedule_outcome_check(state: HackathonState) -> None:
    """Schedule the Outcome Tracker to run after judging day (non-blocking)."""
    try:
        brief = state.get("brief", {})
        deadline_raw = brief.get("deadline", "")
        if not deadline_raw:
            return

        deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
        # Outcomes are typically posted 24-48h after submission deadline
        check_at = deadline + __import__("datetime").timedelta(hours=36)
        now = datetime.now(timezone.utc)

        redis = get_redis()
        await redis.set(
            f"outcome:scheduled:{state['hackathon_id']}",
            json.dumps({
                "hackathon_id": state["hackathon_id"],
                "check_at": check_at.isoformat(),
                "submitted_url": state.get("submission_url", ""),
            }),
            ex=86400 * 7,   # keep for 7 days
        )

        if check_at > now:
            delay_hours = (check_at - now).total_seconds() / 3600
            logger.info(
                f"[forge:commander] Outcome check scheduled for "
                f"{brief.get('name')} in {delay_hours:.1f}h"
            )
        else:
            # Judging already happened — trigger immediately
            await trigger_agent(redis, state["hackathon_id"], "outcome_tracker", {})

        await redis.aclose()
    except Exception as e:
        logger.warning(f"[forge:commander] Could not schedule outcome check: {e}")


# ── Routing ────────────────────────────────────────────────────────────────────

def route_after_intel(state: HackathonState) -> str:
    return "generate_concepts"

def route_after_concepts(state: HackathonState) -> str:
    return "wait_concept_approval"

def route_after_concept_approval(state: HackathonState) -> str:
    if state["errors"]:
        return END
    return "run_planning"

def route_after_planning(state: HackathonState) -> str:
    if state["errors"]:
        return END
    return "run_design"

def route_after_design(state: HackathonState) -> str:
    return "generate_build_plan"

def route_after_build(state: HackathonState) -> str:
    if state["errors"]:
        return END
    return "run_verification"

def route_after_quality(state: HackathonState) -> str:
    return "wait_quality_review"

def route_after_quality_approval(state: HackathonState) -> str:
    return "run_polish"


async def _schedule_outcome_node(state: HackathonState) -> dict:
    """Properly awaited wrapper for schedule_outcome_check."""
    try:
        await schedule_outcome_check(state)
    except Exception as e:
        logger.warning(f"[forge:commander] Outcome scheduling failed: {e}")
    return {}


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(HackathonState)

    g.add_node("run_intelligence",        run_intelligence)
    g.add_node("generate_concepts",       generate_concepts)
    g.add_node("wait_concept_approval",   wait_concept_approval)
    g.add_node("run_planning",            run_planning)
    g.add_node("run_design",              run_design)
    g.add_node("generate_build_plan",     generate_build_plan)
    g.add_node("wait_design_approval",    wait_design_approval)
    g.add_node("run_build",               run_build)
    g.add_node("run_verification",        run_verification)
    g.add_node("wait_quality_review",     wait_quality_review)
    g.add_node("run_polish",              run_polish)
    g.add_node("run_submission",          run_submission)
    g.add_node("schedule_outcome",        _schedule_outcome_node)

    g.add_edge(START, "run_intelligence")
    g.add_conditional_edges("run_intelligence",      route_after_intel)
    g.add_conditional_edges("generate_concepts",     route_after_concepts)
    g.add_conditional_edges("wait_concept_approval", route_after_concept_approval)
    g.add_conditional_edges("run_planning",          route_after_planning)
    g.add_conditional_edges("run_design",            route_after_design)
    g.add_edge("generate_build_plan",   "wait_design_approval")
    g.add_edge("wait_design_approval",  "run_build")
    g.add_conditional_edges("run_build",             route_after_build)
    g.add_conditional_edges("run_verification",      route_after_quality)
    g.add_conditional_edges("wait_quality_review",   route_after_quality_approval)
    g.add_edge("run_polish",     "run_submission")
    g.add_edge("run_submission", "schedule_outcome")
    g.add_edge("schedule_outcome", END)

    return g


# ── Entry point ────────────────────────────────────────────────────────────────

PHASE_ORDER = [
    "intelligence", "strategy", "planning", "design",
    "building", "verifying", "polishing", "submitting", "done",
]

PHASE_TO_NODE: dict[str, str] = {
    "intelligence": "run_intelligence",
    "strategy":     "generate_concepts",
    "planning":     "run_planning",
    "design":       "run_design",
    "building":     "run_build",
    "verifying":    "run_verification",
    "polishing":    "run_polish",
    "submitting":   "run_submission",
}


async def run(
    hackathon_id: str,
    *,
    force_restart: bool = False,
    from_phase: str | None = None,
) -> HackathonState:
    redis = get_redis()
    brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
    await redis.aclose()

    if not brief_raw:
        raise SystemExit(f"No brief for hackathon_id={hackathon_id}")

    brief = json.loads(brief_raw)

    def _make_initial(phase: str = "intelligence") -> HackathonState:
        return {
            "hackathon_id": hackathon_id,
            "brief": brief,
            "intel": {},
            "concepts": {},
            "selected_concept": {},
            "project_plan": {},
            "db_schema": {},
            "api_contract": {},
            "design_spec": {},
            "preview_url": "",
            "repo_url": "",
            "submission_url": "",
            "phase": phase,
            "checkpoint_approvals": {},
            "agent_statuses": {},
            "agent_failures": {},
            "errors": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "messages": [],
        }

    if from_phase and from_phase not in PHASE_TO_NODE:
        valid = ", ".join(PHASE_TO_NODE.keys())
        raise SystemExit(f"Unknown phase '{from_phase}'. Valid phases: {valid}")

    db_url = os.environ["DATABASE_URL"]
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")

    thread_config = {"configurable": {"thread_id": hackathon_id}}

    logger.info(f"[forge:commander] Connecting to PostgreSQL for checkpointing...")
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        logger.info(f"[forge:commander] PostgreSQL connected. Setting up checkpoint tables...")
        await checkpointer.setup()
        logger.info(f"[forge:commander] Checkpoint tables ready. Building execution graph...")
        compiled = build_graph().compile(checkpointer=checkpointer)

        existing = await checkpointer.aget(thread_config)

        if from_phase and existing:
            saved_state = {**existing["channel_values"]}
            saved_state["phase"] = from_phase
            node = PHASE_TO_NODE[from_phase]
            logger.info(
                f"[forge:commander] ═══════════════════════════════════════════════════\n"
                f"[forge:commander]   JUMPING TO PHASE: {from_phase}\n"
                f"[forge:commander]   Hackathon: {brief.get('name')}\n"
                f"[forge:commander]   ID: {hackathon_id}\n"
                f"[forge:commander]   Target node: {node}\n"
                f"[forge:commander]   Preserving state from: {existing['channel_values'].get('phase', '?')}\n"
                f"[forge:commander] ═══════════════════════════════════════════════════"
            )
            result = await compiled.ainvoke(
                saved_state,
                config={**thread_config, "configurable": {**thread_config["configurable"]}},
            )

        elif from_phase and not existing:
            logger.warning(
                f"[forge:commander] No checkpoint found — cannot jump to '{from_phase}'. "
                f"Starting from scratch."
            )
            result = await compiled.ainvoke(_make_initial(), config=thread_config)

        elif not force_restart and existing:
            saved_phase = existing["channel_values"].get("phase", "?")
            logger.info(
                f"[forge:commander] ═══════════════════════════════════════════════════\n"
                f"[forge:commander]   RESUMING: {brief.get('name')}\n"
                f"[forge:commander]   ID: {hackathon_id}\n"
                f"[forge:commander]   Saved phase: {saved_phase}\n"
                f"[forge:commander]   Checkpoint: {existing['id'][:12]}...\n"
                f"[forge:commander] ═══════════════════════════════════════════════════"
            )
            result = await compiled.ainvoke(None, config=thread_config)

        else:
            if force_restart and existing:
                logger.info(f"[forge:commander] Force restart — discarding existing checkpoint")
            logger.info(
                f"[forge:commander] ═══════════════════════════════════════════════════\n"
                f"[forge:commander]   STARTING: {brief.get('name')}\n"
                f"[forge:commander]   ID: {hackathon_id}\n"
                f"[forge:commander]   Theme: {brief.get('theme', '?')}\n"
                f"[forge:commander]   Deadline: {brief.get('days_until_deadline', '?')}d left\n"
                f"[forge:commander]   Graph nodes: {len(compiled.get_graph().nodes)}\n"
                f"[forge:commander] ═══════════════════════════════════════════════════"
            )
            result = await compiled.ainvoke(_make_initial(), config=thread_config)

        logger.info(
            f"[forge:commander] ═══════════════════════════════════════════════════\n"
            f"[forge:commander]   COMPLETE: {brief.get('name')}\n"
            f"[forge:commander]   Final phase: {result.get('phase')}\n"
            f"[forge:commander]   Submission: {result.get('submission_url', 'none')}\n"
            f"[forge:commander]   Errors: {len(result.get('errors', []))}\n"
            f"[forge:commander] ═══════════════════════════════════════════════════"
        )
        return result


async def run_listener() -> None:
    """Listen for new hackathons triggered by Scout."""
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("commander:new_hackathon")
    logger.info("[forge:commander] Listening for new hackathons...")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        hackathon_id = payload.get("hackathon_id")
        if hackathon_id:
            asyncio.create_task(run(hackathon_id))

    await redis.aclose()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Hackathon Commander")
    parser.add_argument("--hackathon-id", help="Run specific hackathon by ID")
    parser.add_argument("--listen", action="store_true", help="Listen for Scout triggers (daemon mode)")
    args = parser.parse_args()

    if args.listen:
        asyncio.run(run_listener())
    elif args.hackathon_id:
        asyncio.run(run(args.hackathon_id))
    else:
        parser.print_help()
