"""Batch operation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from forge_web.schemas import BatchRequest
from forge_web.services import redis_conn, delete_hackathon, reroll_hackathon

router = APIRouter()


@router.post("/api/hackathon/batch")
async def api_batch(body: BatchRequest):
    if body.action not in ("delete", "reroll"):
        raise HTTPException(400, detail=f"Unknown action: {body.action}")

    async with redis_conn() as redis:
        results = []
        for hid in body.ids:
            try:
                if body.action == "delete":
                    result = await delete_hackathon(redis, hid)
                else:
                    result = await reroll_hackathon(redis, hid)
                results.append(result)
            except Exception as exc:
                results.append({"id": hid, "success": False, "error": str(exc)})
        return {"ok": True, "results": results}
