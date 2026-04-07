"""Redis service helpers — shared business logic for the Forge web API."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from config.redis_client import get_redis
from forge_web.constants import LAYER_AGENTS, AGENT_TO_PHASE

logger = logging.getLogger("forge.web")


@asynccontextmanager
async def redis_conn():
    """Async context manager for a Redis connection with auto-close."""
    r = get_redis()
    try:
        yield r
    finally:
        await r.aclose()


# ── Phase derivation ─────────────────────────────────────────────────────────

async def derive_phase(redis, hackathon_id: str) -> str:
    phase_order = ["intelligence", "strategy", "design", "build", "verify", "polish", "submission", "infra"]
    for phase_name in phase_order:
        agents = LAYER_AGENTS.get(phase_name, [])
        all_done = True
        for agent_id in agents:
            raw = await redis.get(f"task:{hackathon_id}:{agent_id}")
            if raw:
                try:
                    data = json.loads(raw)
                    if data.get("status") != "done":
                        all_done = False
                except Exception:
                    all_done = False
            else:
                all_done = False
        if not all_done:
            return phase_name
    return "submission"


# ── Hackathon listing ────────────────────────────────────────────────────────

async def get_hackathons(redis) -> list[dict]:
    keys = await redis.keys("hackathon:*:brief")
    hacks = []
    for key in sorted(keys):
        hid = key.split(":")[1]
        brief_raw = await redis.get(key)
        brief = json.loads(brief_raw) if brief_raw else {}
        explicit = await redis.get(f"hackathon:{hid}:phase")
        if explicit and explicit != "unknown":
            phase = explicit
        else:
            phase = await derive_phase(redis, hid)
        hacks.append({"id": hid, "brief": brief, "phase": phase})
    return hacks


# ── Checkpoints ──────────────────────────────────────────────────────────────

async def get_checkpoints(redis) -> list[dict]:
    keys = await redis.keys("checkpoint:*:*")
    checkpoints = []
    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) < 3:
            continue
        hid, cp_name = parts[1], parts[2]
        raw = await redis.get(key)
        is_pending = raw == "pending"
        data = {}
        if raw and raw != "pending":
            try:
                data = json.loads(raw)
            except Exception:
                pass

        if is_pending or not data:
            enriched = await enrich_checkpoint(redis, hid, cp_name)
            if enriched:
                data = {**data, **enriched}

        checkpoints.append({
            "hackathon_id": hid,
            "checkpoint": cp_name,
            "pending": is_pending,
            "data": data,
        })
    return checkpoints


async def enrich_checkpoint(redis, hackathon_id: str, cp_name: str) -> dict:
    """Pull relevant data from agent task outputs to enrich a checkpoint."""
    try:
        if cp_name == "concept_approval":
            raw = await redis.get(f"task:{hackathon_id}:strategy_director")
            if raw:
                task = json.loads(raw)
                task_data = task.get("data", {})
                concepts = task_data.get("concepts", [])
                if concepts:
                    return {
                        "concepts": concepts,
                        "recommended_concept": task_data.get("recommended_concept", 1),
                        "reasoning": task_data.get("reasoning", ""),
                        "analysis": task_data.get("analysis", ""),
                    }
        elif cp_name == "design_approval":
            raw = await redis.get(f"task:{hackathon_id}:ui_ux_designer")
            if raw:
                task = json.loads(raw)
                task_data = task.get("data", {})
                if task_data:
                    return {
                        "personality": task_data.get("personality", ""),
                        "screen_count": task_data.get("screen_count", 0),
                        "component_count": task_data.get("component_count", 0),
                        "screens": task_data.get("screens", []),
                    }
        elif cp_name == "quality_review":
            raw = await redis.get(f"task:{hackathon_id}:ux_auditor")
            if raw:
                task = json.loads(raw)
                task_data = task.get("data", {})
                if task_data:
                    return {
                        "overall_score": task_data.get("overall_score"),
                        "approved": task_data.get("approved"),
                        "blockers": task_data.get("blockers", []),
                    }
    except Exception:
        pass
    return {}


# ── Delete / reroll ──────────────────────────────────────────────────────────

async def _clear_extra_keys(redis, hackathon_id: str) -> int:
    """Delete trace/cost/artifact keys that the original delete/reroll missed."""
    deleted = 0
    for exact in [
        f"spans:{hackathon_id}",
        f"events:{hackathon_id}",
        f"artifacts:{hackathon_id}",
    ]:
        if await redis.exists(exact):
            deleted += await redis.delete(exact)
    for pattern in [f"cost:{hackathon_id}:*"]:
        keys = await redis.keys(pattern)
        if keys:
            deleted += await redis.delete(*keys)
    return deleted


async def _clear_postgres_checkpoint(hackathon_id: str) -> None:
    """Delete the LangGraph Postgres checkpoint for this hackathon thread."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    clean_url = (
        db_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
    )
    try:
        import asyncpg
        conn = await asyncpg.connect(clean_url)
        try:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                await conn.execute(
                    f"DELETE FROM {table} WHERE thread_id = $1", hackathon_id,
                )
        finally:
            await conn.close()
        logger.info(f"Cleared Postgres checkpoint for {hackathon_id}")
    except Exception as exc:
        logger.warning(f"Could not clear Postgres checkpoint for {hackathon_id}: {exc}")


async def delete_hackathon(redis, hackathon_id: str) -> dict:
    brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
    if not brief_raw:
        return {"id": hackathon_id, "success": False, "error": "not found"}

    name = "?"
    try:
        name = json.loads(brief_raw).get("name", "?")
    except Exception:
        pass

    deleted = 0
    for pattern in [
        f"hackathon:{hackathon_id}:*",
        f"task:{hackathon_id}:*",
        f"checkpoint:{hackathon_id}:*",
        f"logs:{hackathon_id}",
    ]:
        keys = await redis.keys(pattern)
        if keys:
            deleted += await redis.delete(*keys)
    deleted += await _clear_extra_keys(redis, hackathon_id)
    await _clear_postgres_checkpoint(hackathon_id)
    return {"id": hackathon_id, "success": True, "name": name, "keys_deleted": deleted}


async def reroll_hackathon(redis, hackathon_id: str) -> dict:
    brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
    if not brief_raw:
        return {"id": hackathon_id, "success": False, "error": "not found"}

    name = json.loads(brief_raw).get("name", "?")

    # Increment epoch so any in-flight agents discard their writes
    new_epoch = await redis.incr(f"hackathon:{hackathon_id}:epoch")

    agents_to_clear = [
        "strategy_director", "pm", "tech_architect", "ui_ux_designer",
        "frontend_engineer", "backend_engineer", "integration_engineer",
        "test_engineer", "devops", "security",
    ]
    checkpoints_to_clear = ["concept_approval", "design_approval", "quality_review"]

    cleared = 0
    for agent in agents_to_clear:
        key = f"task:{hackathon_id}:{agent}"
        if await redis.exists(key):
            await redis.delete(key)
            cleared += 1
    for cp in checkpoints_to_clear:
        key = f"checkpoint:{hackathon_id}:{cp}"
        if await redis.exists(key):
            await redis.delete(key)
            cleared += 1

    concepts_key = f"hackathon:{hackathon_id}:concepts"
    if await redis.exists(concepts_key):
        await redis.delete(concepts_key)
        cleared += 1

    cleared += await _clear_extra_keys(redis, hackathon_id)
    await _clear_postgres_checkpoint(hackathon_id)

    return {
        "id": hackathon_id, "success": True, "name": name,
        "keys_cleared": cleared, "epoch": new_epoch,
    }


# ── Analytics builder ────────────────────────────────────────────────────────

async def build_analytics(redis, hackathon_filter: str | None = None) -> dict:
    if hackathon_filter:
        brief_keys = [f"hackathon:{hackathon_filter}:brief"]
    else:
        brief_keys = sorted(await redis.keys("hackathon:*:brief"))

    cost_by_hackathon = []
    daily_runs: dict[str, int] = {}
    for bk in brief_keys:
        raw = await redis.get(bk)
        if not raw:
            continue
        try:
            brief = json.loads(raw)
        except Exception:
            continue
        hid = bk.split(":")[1]
        cost = brief.get("cost_usd") or brief.get("total_cost") or 0
        cost_by_hackathon.append({"name": brief.get("name", hid), "cost_usd": cost})
        created = brief.get("created_at") or brief.get("started_at") or ""
        if created:
            day = created[:10]
            daily_runs[day] = daily_runs.get(day, 0) + 1

    if hackathon_filter:
        task_keys = sorted(await redis.keys(f"task:{hackathon_filter}:*"))
    else:
        task_keys = sorted(await redis.keys("task:*:*"))

    agent_times: dict[str, list[float]] = {}
    agent_success: dict[str, dict[str, int]] = {}
    for tk in task_keys:
        agent_id = tk.split(":")[-1]
        raw = await redis.get(tk)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue

        status = parsed.get("status", "")
        if agent_id not in agent_success:
            agent_success[agent_id] = {"success": 0, "total": 0}
        agent_success[agent_id]["total"] += 1
        if status == "done":
            agent_success[agent_id]["success"] += 1

        started = parsed.get("started_at")
        finished = parsed.get("finished_at")
        if started and finished:
            try:
                dt = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
                agent_times.setdefault(agent_id, []).append(dt)
            except Exception:
                pass

    agent_timing = []
    for aid, times in sorted(agent_times.items()):
        agent_timing.append({"agent_id": aid, "avg_seconds": round(sum(times) / len(times), 1)})

    success_rates = []
    for aid, counts in sorted(agent_success.items()):
        total = counts["total"]
        pct = round(counts["success"] / total * 100, 1) if total else 0
        success_rates.append({"agent_id": aid, "success_pct": pct, "total_runs": total})

    daily_list = [{"date": d, "count": c} for d, c in sorted(daily_runs.items())]

    return {
        "cost_by_hackathon": cost_by_hackathon,
        "agent_timing": agent_timing,
        "success_rates": success_rates,
        "daily_runs": daily_list,
    }
