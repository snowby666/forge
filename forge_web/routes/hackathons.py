"""Hackathon CRUD and approval endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from forge_web.services import (
    redis_conn, get_hackathons, delete_hackathon, reroll_hackathon,
)

router = APIRouter()


@router.get("/api/hackathons")
async def api_hackathons():
    async with redis_conn() as redis:
        return await get_hackathons(redis)


@router.delete("/api/hackathon/{hackathon_id}")
async def api_delete_hackathon(hackathon_id: str):
    async with redis_conn() as redis:
        result = await delete_hackathon(redis, hackathon_id)
        if not result.get("success"):
            raise HTTPException(404, detail="Hackathon not found")
        return {"ok": True, **result}


@router.post("/api/hackathon/{hackathon_id}/reroll")
async def api_reroll(hackathon_id: str):
    async with redis_conn() as redis:
        result = await reroll_hackathon(redis, hackathon_id)
        if not result.get("success"):
            raise HTTPException(404, detail="Hackathon not found")
        return {
            "ok": True,
            **result,
            "message": f"Cleared strategy/design state. Run: forge run --id {hackathon_id}",
        }


@router.post("/api/approve/{hackathon_id}/{checkpoint}")
async def api_approve(hackathon_id: str, checkpoint: str, request: Request):
    async with redis_conn() as redis:
        key = f"checkpoint:{hackathon_id}:{checkpoint}"
        raw = await redis.get(key)
        if not raw:
            raise HTTPException(404, "Checkpoint not found")

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        approval = {
            "approved": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": "web",
        }
        if checkpoint == "concept_approval":
            approval["concept_index"] = body.get("concept_index", 0)

        await redis.set(key, json.dumps(approval), ex=86400)
        return {"ok": True, "hackathon_id": hackathon_id, "checkpoint": checkpoint}
