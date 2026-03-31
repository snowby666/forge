"""
config/run_context.py — Runtime context injection for Forge agents
===================================================================
Adapted from Claude Code's src/context.ts

CC collects OS/shell/git state and injects it into every system prompt.
Forge adapts this for the hackathon context: deadline pressure, run health,
current cost, failed agents, UX audit score — all the runtime facts that
should change how agents behave.

Usage:
    from config.run_context import build_run_context
    ctx = await build_run_context(hackathon_id, redis)
    system_prompt = AGENT.system_prompt + ctx
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


async def build_run_context(hackathon_id: str, redis: Redis) -> str:
    """
    Build a runtime context block to inject into an agent's system prompt.

    Returns a markdown section with:
    - Deadline pressure (hours remaining)
    - Current run cost and token usage
    - Any agents that have already failed this run
    - Last UX audit score (if available)
    - Current phase

    Only includes non-empty sections — won't add noise to early-phase agents.
    """
    lines: list[str] = []

    # ── 1. Deadline pressure ──────────────────────────────────────────────────
    try:
        brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
        if brief_raw:
            brief = json.loads(brief_raw)
            deadline_raw = brief.get("deadline", "")
            if deadline_raw:
                deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                hours_left = (deadline - now).total_seconds() / 3600
                if hours_left < 0:
                    lines.append(f"- **Deadline PASSED** {abs(hours_left):.0f}h ago — submission closed")
                elif hours_left < 4:
                    lines.append(f"- **CRITICAL: {hours_left:.1f}h until deadline** — prioritize demo path only")
                elif hours_left < 12:
                    lines.append(f"- **{hours_left:.0f}h until deadline** — reduce scope if needed, quality over features")
                else:
                    lines.append(f"- {hours_left:.0f}h until submission deadline")
    except Exception as e:
        logger.debug(f"[forge:context] Deadline check failed: {e}")

    # ── 2. Failed agents this run ─────────────────────────────────────────────
    try:
        task_keys = await redis.keys(f"task:{hackathon_id}:*")
        failed_agents = []
        for key in task_keys:
            raw = await redis.get(key)
            if raw:
                task = json.loads(raw)
                if task.get("status") == "failed":
                    agent_id = key.split(":")[-1]
                    failed_agents.append(agent_id)
        if failed_agents:
            lines.append(f"- **Agents that failed this run:** {', '.join(failed_agents)} — work around their missing outputs")
    except Exception as e:
        logger.debug(f"[forge:context] Failed agents check failed: {e}")

    # ── 3. UX audit score ─────────────────────────────────────────────────────
    try:
        audit_raw = await redis.get(f"task:{hackathon_id}:ux_auditor")
        if audit_raw:
            audit = json.loads(audit_raw)
            audit_data = audit.get("data", {})
            score = audit_data.get("overall_score")
            if score is not None:
                approved = audit_data.get("approved", False)
                status = "approved" if approved else "BLOCKED"
                lines.append(f"- UX Audit score: {score:.1f}/10 ({status})")
                if not approved:
                    blockers = audit_data.get("blockers", [])
                    if blockers:
                        lines.append(f"  Blockers: {'; '.join(blockers[:3])}")
    except Exception as e:
        logger.debug(f"[forge:context] UX audit check failed: {e}")

    # ── 4. Current cost ───────────────────────────────────────────────────────
    try:
        cost_keys = await redis.keys(f"cost:{hackathon_id}:*")
        total_usd = 0.0
        for key in cost_keys:
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                total_usd += data.get("total_cost_usd", 0.0)
        if total_usd > 0.50:
            lines.append(f"- Run cost so far: ${total_usd:.2f}")
            if total_usd > 8.0:
                lines.append("  **Approaching $10 budget limit** — prefer bulk/fast tier calls")
    except Exception as e:
        logger.debug(f"[forge:context] Cost check failed: {e}")

    # ── 5. Current phase ──────────────────────────────────────────────────────
    try:
        for phase_agent in ["submission", "polish", "ux_auditor", "frontend_engineer", "ui_ux_designer", "tech_architect"]:
            raw = await redis.get(f"task:{hackathon_id}:{phase_agent}")
            if raw:
                task = json.loads(raw)
                if task.get("status") == "done":
                    phase_map = {
                        "submission": "submitted",
                        "polish": "polish complete",
                        "ux_auditor": "verification",
                        "frontend_engineer": "build complete",
                        "ui_ux_designer": "design complete",
                        "tech_architect": "planning complete",
                    }
                    lines.append(f"- Current phase: {phase_map.get(phase_agent, phase_agent)}")
                    break
    except Exception as e:
        logger.debug(f"[forge:context] Phase check failed: {e}")

    if not lines:
        return ""

    return "\n\n## Current run context\n" + "\n".join(lines) + "\n"


async def build_memdir_context_for_agent(agent_id: str) -> str:
    """
    Build memdir context for a specific agent.
    Thin wrapper that handles missing FORGE_MEMDIR gracefully.
    """
    try:
        from config.forge_tools import build_memdir_context
        return build_memdir_context(agent_id)
    except Exception:
        return ""
