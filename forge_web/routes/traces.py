"""Trace spans, log events, unified event stream, and artifact registry endpoints."""

from __future__ import annotations

import json
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
    kind: str | None = Query(None, description="Filter by kind: 'log' or 'span'"),
    agent: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """Unified event stream — both logs and spans interleaved."""
    async with redis_conn() as redis:
        events = await _load_events(redis, hackathon_id)
        filtered = []
        for ev in events:
            if kind and ev.get("kind") != kind:
                continue
            if agent and ev.get("agent_id") != agent:
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
    """Return only span-kind events (backward-compatible with existing trace-viewer)."""
    async with redis_conn() as redis:
        events = await _load_events(redis, hackathon_id)
        spans = []
        for ev in events:
            if ev.get("kind") != "span":
                continue
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
        total_log_events = 0
        total_span_events = 0

        for ev in events:
            kind = ev.get("kind", "span")
            if kind == "log":
                total_log_events += 1
                if ev.get("level") == "error":
                    error_count += 1
                continue

            total_span_events += 1
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
            "total_spans": total_span_events,
            "total_logs": total_log_events,
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
