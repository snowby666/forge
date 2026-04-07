"""Traces, events, artifacts, cost, and elapsed time endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query

from forge_web.services import redis_conn

router = APIRouter()

EVENTS_KEY = "events"


async def _load_events(redis, hackathon_id: str) -> list[dict]:
    """Load all events from the unified events list."""
    raw_entries = await redis.lrange(f"{EVENTS_KEY}:{hackathon_id}", 0, -1)
    events: list[dict] = []
    for entry in raw_entries:
        try:
            events.append(json.loads(entry))
        except Exception:
            continue
    return events


@router.get("/api/hackathon/{hackathon_id}/events")
async def api_events(
    hackathon_id: str,
    agent: str | None = Query(None),
    op: str | None = Query(None, description="Filter by op type: llm, mcp, log, etc."),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """Unified event stream — all events are trace spans."""
    async with redis_conn() as redis:
        events = await _load_events(redis, hackathon_id)
        filtered = []
        for ev in events:
            if agent and ev.get("agent_id") != agent:
                continue
            if op and ev.get("op") != op:
                continue
            filtered.append(ev)
        total = len(filtered)
        return {"total": total, "offset": offset, "limit": limit, "events": filtered[offset:offset + limit]}


@router.get("/api/hackathon/{hackathon_id}/traces")
async def api_traces(
    hackathon_id: str,
    agent: str | None = Query(None),
    op: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """Return trace spans with optional filters."""
    async with redis_conn() as redis:
        events = await _load_events(redis, hackathon_id)
        spans = []
        for ev in events:
            if agent and ev.get("agent_id") != agent:
                continue
            if op and ev.get("op") != op:
                continue
            if status and ev.get("status") != status:
                continue
            spans.append(ev)

        total = len(spans)
        paginated = spans[offset : offset + limit]
        return {"total": total, "offset": offset, "limit": limit, "spans": paginated}


@router.get("/api/hackathon/{hackathon_id}/traces/summary")
async def api_traces_summary(hackathon_id: str):
    async with redis_conn() as redis:
        events = await _load_events(redis, hackathon_id)
        by_op: dict[str, int] = {}
        by_agent: dict[str, int] = {}
        total_llm_tokens = 0
        total_llm_cost_usd = 0.0
        total_file_writes = 0
        error_count = 0

        for ev in events:
            op = ev.get("op", "unknown")
            aid = ev.get("agent_id", "unknown")
            by_op[op] = by_op.get(op, 0) + 1
            by_agent[aid] = by_agent.get(aid, 0) + 1

            if ev.get("status") == "error":
                error_count += 1

            if op == "llm":
                output = ev.get("output", {})
                total_llm_tokens += output.get("prompt_tokens", 0) + output.get("completion_tokens", 0)

            if op == "file":
                total_file_writes += 1

        cost_keys = await redis.keys(f"cost:{hackathon_id}:*")
        for key in cost_keys:
            raw = await redis.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                    total_llm_cost_usd += data.get("total_cost_usd", 0.0)
                except Exception:
                    pass

        return {
            "total_spans": len(events),
            "by_op": by_op,
            "by_agent": by_agent,
            "total_llm_tokens": total_llm_tokens,
            "total_llm_cost_usd": round(total_llm_cost_usd, 4),
            "total_file_writes": total_file_writes,
            "error_count": error_count,
        }


@router.get("/api/hackathon/{hackathon_id}/artifact-registry")
async def api_artifact_registry(hackathon_id: str):
    async with redis_conn() as redis:
        raw = await redis.hgetall(f"artifacts:{hackathon_id}")
        artifacts = []
        for name, val in sorted(raw.items()):
            try:
                entry = json.loads(val)
                artifacts.append(entry)
            except Exception:
                artifacts.append({"name": name, "type": "unknown", "agent_id": "unknown", "timestamp": "", "summary": str(val)[:200]})
        return artifacts


# ── Cost & Elapsed (moved from logs.py) ──────────────────────────────────────

@router.get("/api/hackathon/{hackathon_id}/cost")
async def api_cost(hackathon_id: str):
    async with redis_conn() as redis:
        keys = await redis.keys(f"cost:{hackathon_id}:*")
        total_usd = 0.0
        total_tokens = 0
        by_agent: dict[str, Any] = {}
        for key in keys:
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                aid = data.get("agent_id", key.split(":")[-1])
                cost = data.get("total_cost_usd", 0.0)
                tokens = data.get("total_input_tokens", 0) + data.get("total_output_tokens", 0)
                by_agent[aid] = {
                    "cost_usd": round(cost, 4),
                    "input_tokens": data.get("total_input_tokens", 0),
                    "output_tokens": data.get("total_output_tokens", 0),
                    "tokens": tokens,
                    "calls": data.get("calls", 0),
                }
                total_usd += cost
                total_tokens += tokens
        return {
            "total_usd": round(total_usd, 4),
            "total_tokens": total_tokens,
            "by_agent": by_agent,
        }


@router.get("/api/hackathon/{hackathon_id}/elapsed")
async def api_elapsed(hackathon_id: str):
    async with redis_conn() as redis:
        keys = await redis.keys(f"task:{hackathon_id}:*")
        earliest_start: str | None = None
        latest_finish: str | None = None
        agent_times: list[dict[str, Any]] = []
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            started = data.get("started_at")
            finished = data.get("finished_at")
            agent_id = key.split(":")[-1]
            elapsed_s = data.get("elapsed_s")
            if started:
                if not earliest_start or started < earliest_start:
                    earliest_start = started
                if finished and (not latest_finish or finished > latest_finish):
                    latest_finish = finished
            if elapsed_s is not None:
                agent_times.append({"agent_id": agent_id, "elapsed_s": elapsed_s, "status": data.get("status")})

        total_elapsed = None
        if earliest_start:
            try:
                t0 = datetime.fromisoformat(earliest_start)
                t1 = datetime.fromisoformat(latest_finish) if latest_finish else datetime.now(timezone.utc)
                total_elapsed = round((t1 - t0).total_seconds(), 1)
            except Exception:
                pass

        return {
            "total_elapsed_s": total_elapsed,
            "started_at": earliest_start,
            "latest_finish": latest_finish,
            "agent_times": sorted(agent_times, key=lambda x: x.get("elapsed_s", 0), reverse=True),
        }
