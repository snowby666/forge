"""Logs, cost tracking, and elapsed time endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query

from forge_web.services import redis_conn

router = APIRouter()


@router.get("/api/hackathon/{hackathon_id}/logs")
async def api_logs(
    hackathon_id: str,
    agent: str | None = Query(None),
    level: str | None = Query(None),
):
    async with redis_conn() as redis:
        raw_entries = await redis.lrange(f"events:{hackathon_id}", -2000, -1)
        logs = []
        for entry in raw_entries:
            try:
                parsed = json.loads(entry)
            except Exception:
                continue
            if parsed.get("kind") != "log":
                continue
            if agent and parsed.get("agent_id") != agent:
                continue
            if level and parsed.get("level") != level:
                continue
            logs.append(parsed)
        return logs[-500:]


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
