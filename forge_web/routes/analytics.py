"""Analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from forge_web.services import redis_conn, build_analytics

router = APIRouter()


@router.get("/api/analytics")
async def api_analytics():
    async with redis_conn() as redis:
        return await build_analytics(redis)


@router.get("/api/analytics/{hackathon_id}")
async def api_analytics_hackathon(hackathon_id: str):
    async with redis_conn() as redis:
        return await build_analytics(redis, hackathon_filter=hackathon_id)
