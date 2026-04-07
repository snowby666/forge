"""Agent status, trigger, and restart endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter

from forge_web.constants import AGENT_TO_PHASE
from forge_web.services import redis_conn

router = APIRouter()


@router.get("/api/hackathon/{hackathon_id}/agents")
async def api_agents(hackathon_id: str):
    async with redis_conn() as redis:
        keys = await redis.keys(f"task:{hackathon_id}:*")
        agents = []
        for key in sorted(keys):
            agent_id = key.split(":")[-1]
            raw = await redis.get(key)
            status = "unknown"
            phase = AGENT_TO_PHASE.get(agent_id, "unknown")
            elapsed = None
            data = None
            if raw:
                try:
                    parsed = json.loads(raw)
                    status = parsed.get("status", "unknown")
                    data = parsed
                    started = parsed.get("started_at")
                    finished = parsed.get("finished_at")
                    if started:
                        end = finished or datetime.now(timezone.utc).isoformat()
                        try:
                            t0 = datetime.fromisoformat(started)
                            t1 = datetime.fromisoformat(end)
                            elapsed = round((t1 - t0).total_seconds(), 1)
                        except Exception:
                            pass
                except Exception:
                    status = raw
            started_at = parsed.get("started_at") if data else None
            finished_at = parsed.get("finished_at") if data else None
            elapsed_s = parsed.get("elapsed_s") if data else None
            if elapsed_s is None and elapsed is not None:
                elapsed_s = elapsed
            agents.append({
                "agent_id": agent_id,
                "status": status,
                "phase": phase,
                "elapsed": elapsed,
                "elapsed_s": elapsed_s,
                "started_at": started_at,
                "finished_at": finished_at,
                "data": data,
            })
        return agents


@router.post("/api/hackathon/{hackathon_id}/agent/{agent_id}/trigger")
async def api_trigger_agent(hackathon_id: str, agent_id: str):
    async with redis_conn() as redis:
        await redis.publish("agent:trigger", json.dumps({
            "hackathon_id": hackathon_id,
            "agent": agent_id,
            "input": {},
        }))
        return {"ok": True}


@router.post("/api/hackathon/{hackathon_id}/agent/{agent_id}/restart")
async def api_restart_agent(hackathon_id: str, agent_id: str):
    async with redis_conn() as redis:
        await redis.delete(f"task:{hackathon_id}:{agent_id}")
        await redis.publish("agent:trigger", json.dumps({
            "hackathon_id": hackathon_id,
            "agent": agent_id,
            "input": {},
        }))
        return {"ok": True}
