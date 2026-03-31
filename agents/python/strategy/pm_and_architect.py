# -*- coding: utf-8 -*-
"""
PM Agent + Tech Architect — Layer 2: Strategy
Both run after concept approval checkpoint.
PM produces ProjectPlan; Architect produces DbSchema + ApiContract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from config.electronhub import complete_json
from config.agents_config import ALL_AGENTS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PM AGENT
# ─────────────────────────────────────────────────────────────────────────────

class AcceptanceCriteria(BaseModel):
    criterion: str
    demo_moment: str        # the exact screen/action that shows this works


class Feature(BaseModel):
    name: str
    user_story: str         # "As a [persona], I want to [action], so that [outcome]"
    acceptance_criteria: list[AcceptanceCriteria]
    demo_wow_moment: str    # the 5-10 second moment judges remember
    estimated_hours: float  # realistic build estimate
    is_core: bool           # True = build no matter what; False = cut if behind


class ProjectPlan(BaseModel):
    project_name: str
    tagline: str            # starts with verb, ≤12 words
    problem: str            # specific, with numbers
    solution: str           # concrete actions, not adjectives
    target_user: str        # specific persona
    core_features: list[Feature]    # EXACTLY 2
    demo_mode_description: str      # how demo works without login
    demo_golden_path: list[str]     # ordered steps for 90-second demo
    sponsor_integrations: list[dict]
    tech_stack: dict
    timeline: dict          # phase → hours, always sums to total with 25% polish
    total_hours_available: float
    cutscope_decisions: list[str]   # what was deliberately cut and why


async def create_project_plan(
    hackathon_id: str,
    brief: dict,
    selected_concept: dict,
    judge_profile: dict,
    sponsor_map: dict,
    redis: Redis,
) -> ProjectPlan:
    from config.run_context import build_run_context, build_memdir_context_for_agent
    AGENT = ALL_AGENTS["pm"]

    # Feature 2: inject runtime context
    run_ctx = await build_run_context(hackathon_id, redis)
    memdir_ctx = await build_memdir_context_for_agent("pm")

    plan = await complete_json(
        task="create-sprint-plan",
        response_model=ProjectPlan,
        system_prompt=AGENT.system_prompt + run_ctx + memdir_ctx,
        messages=[{
            "role": "user",
            "content": f"""Create the detailed project plan for the approved concept.

Hackathon: {brief.get('name')}
Deadline: {brief.get('deadline')}
Theme: {brief.get('theme')}

Approved concept:
{json.dumps(selected_concept, indent=2)}

Judge panel notes: {json.dumps(judge_profile, indent=2)[:800]}

Sponsor integrations available:
{json.dumps(sponsor_map.get('recommended_integrations', []), indent=2)}

HARD CONSTRAINTS:
- Exactly 2 core features. No more. No exceptions.
- 25% of available time MUST be reserved for polish + submission
- Demo golden path must complete in ≤ 90 seconds
- Demo works without user registration (demo mode)
- tagline must start with a verb

CUTSCOPE: Be explicit about what you're NOT building and why.
Better to know upfront than to run out of time mid-hackathon.""",
        }],
        temperature=0.2,
    )

    await redis.set(f"hackathon:{hackathon_id}:project_plan", plan.model_dump_json(), ex=604800)
    logger.info(f"[forge:pm] Plan created: {plan.project_name}, {len(plan.core_features)} features, {plan.total_hours_available}h available")
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# TECH ARCHITECT
# ─────────────────────────────────────────────────────────────────────────────

class DbTable(BaseModel):
    name: str
    columns: list[dict]     # {name, type, nullable, default, index}
    relationships: list[str]
    demo_seed_rows: int     # how many demo rows to create


class DbSchema(BaseModel):
    tables: list[DbTable]
    migrations: list[str]   # Alembic migration commands in order
    indexes: list[str]      # CREATE INDEX statements
    demo_seed_strategy: str  # how demo data will be structured


class ApiEndpoint(BaseModel):
    method: str             # GET | POST | PUT | DELETE | PATCH
    path: str               # e.g. /api/v1/issues
    summary: str
    description: str
    auth_required: bool
    request_body: dict | None = None
    response_schema: dict
    tags: list[str]
    is_demo_path: bool      # True if this endpoint is called during the demo


class ApiContract(BaseModel):
    base_url: str           # http://localhost:8000 for dev, Railway URL for prod
    version: str = "v1"
    endpoints: list[ApiEndpoint]
    schemas: dict           # Pydantic schema definitions
    demo_endpoints: list[str]  # paths called during demo golden path


class DependencyGraph(BaseModel):
    frontend_can_start_after: list[str]  # artifact types that unlock frontend
    backend_can_start_immediately: bool
    integration_depends_on: list[str]
    parallel_tracks: list[list[str]]     # tracks that can run simultaneously


async def design_architecture(
    hackathon_id: str,
    project_plan: dict,
    redis: Redis,
) -> tuple[DbSchema, ApiContract, DependencyGraph]:
    from config.run_context import build_run_context, build_memdir_context_for_agent
    AGENT = ALL_AGENTS["tech_architect"]

    # Feature 2: inject runtime context so architect knows deadline pressure
    run_ctx = await build_run_context(hackathon_id, redis)
    memdir_ctx = await build_memdir_context_for_agent("tech_architect")

    class ArchitectureOutput(BaseModel):
        db_schema: DbSchema
        api_contract: ApiContract
        dependency_graph: DependencyGraph

    arch = await complete_json(
        task="design-api-contract",
        response_model=ArchitectureOutput,
        system_prompt=AGENT.system_prompt + run_ctx + memdir_ctx,
        messages=[{
            "role": "user",
            "content": f"""Design the complete technical architecture for this project.

Project: {project_plan.get('project_name')} — {project_plan.get('tagline')}
Features: {json.dumps([f.get('name') for f in project_plan.get('core_features', [])], indent=2)}
Demo golden path: {json.dumps(project_plan.get('demo_golden_path', []), indent=2)}
Demo mode: {project_plan.get('demo_mode_description')}

REQUIREMENTS:
- PostgreSQL schema with exactly the tables needed (no speculative future tables)
- FastAPI + SQLAlchemy 2.0 async endpoints
- Include /demo/seed endpoint (creates realistic demo data, idempotent)
- Include /health endpoint
- CORS configured for *.vercel.app
- Mark every endpoint that is called during the demo golden path
- Output the dependency_graph so Commander knows what can run in parallel

PUBLISH IMMEDIATELY: The API contract should be published to Redis right away
so the frontend engineer can start working in parallel with backend implementation.""",
        }],
        temperature=0.1,
    )

    # Store all 3 artifacts
    await redis.set(f"hackathon:{hackathon_id}:db_schema", arch.db_schema.model_dump_json(), ex=604800)
    await redis.set(f"hackathon:{hackathon_id}:api_contract", arch.api_contract.model_dump_json(), ex=604800)
    await redis.set(f"hackathon:{hackathon_id}:dependency_graph", arch.dependency_graph.model_dump_json(), ex=604800)

    # IMMEDIATELY publish api_contract so frontend can unblock
    await redis.publish("agent:api_contract_ready", json.dumps({
        "hackathon_id": hackathon_id,
        "api_contract": arch.api_contract.model_dump(),
    }))

    logger.info(
        f"[forge:architect] Done: {len(arch.db_schema.tables)} tables, "
        f"{len(arch.api_contract.endpoints)} endpoints, "
        f"{len(arch.api_contract.demo_endpoints)} on demo path"
    )
    return arch.db_schema, arch.api_contract, arch.dependency_graph


# ─────────────────────────────────────────────────────────────────────────────
# REDIS WORKERS
# ─────────────────────────────────────────────────────────────────────────────

async def run_pm_worker() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger")
    logger.info("[forge:pm] Worker ready")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        if payload.get("agent") != "pm":
            continue

        hackathon_id = payload["hackathon_id"]
        inp = payload["input"]
        await redis.set(f"task:{hackathon_id}:pm", json.dumps({"status": "in-progress"}), ex=604800)

        try:
            plan = await create_project_plan(
                hackathon_id=hackathon_id,
                brief=inp["brief"],
                selected_concept=inp["selected_concept"],
                judge_profile=inp.get("judge_profile", {}),
                sponsor_map=inp.get("sponsor_map", {}),
                redis=redis,
            )
            await redis.set(
                f"task:{hackathon_id}:pm",
                json.dumps({"status": "done", "data": plan.model_dump()}),
                ex=604800,
            )
        except Exception as e:
            logger.error(f"[forge:pm] Failed: {e}", exc_info=True)
            await redis.set(f"task:{hackathon_id}:pm", json.dumps({"status": "failed", "error": str(e)}), ex=604800)

    await redis.aclose()


async def run_architect_worker() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger")
    logger.info("[forge:architect] Worker ready")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        if payload.get("agent") != "tech_architect":
            continue

        hackathon_id = payload["hackathon_id"]
        inp = payload["input"]
        await redis.set(f"task:{hackathon_id}:tech_architect", json.dumps({"status": "in-progress"}), ex=604800)

        try:
            db_schema, api_contract, dep_graph = await design_architecture(
                hackathon_id=hackathon_id,
                project_plan=inp["project_plan"],
                redis=redis,
            )
            await redis.set(
                f"task:{hackathon_id}:tech_architect",
                json.dumps({"status": "done", "data": {"endpoints": len(api_contract.endpoints)}}),
                ex=604800,
            )
        except Exception as e:
            logger.error(f"[forge:architect] Failed: {e}", exc_info=True)
            await redis.set(f"task:{hackathon_id}:tech_architect", json.dumps({"status": "failed", "error": str(e)}), ex=604800)

    await redis.aclose()
