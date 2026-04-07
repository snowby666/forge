"""Checkpoint listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from forge_web.services import redis_conn, get_checkpoints

router = APIRouter()


@router.get("/api/checkpoints")
async def api_checkpoints():
    async with redis_conn() as redis:
        return await get_checkpoints(redis)
