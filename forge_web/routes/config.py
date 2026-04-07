"""Config read/write endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter

from forge_web.constants import CONFIG_KEYS
from forge_web.schemas import ConfigUpdateRequest
from forge_web.services import redis_conn

router = APIRouter()


@router.get("/api/config")
async def api_config_read():
    async with redis_conn() as redis:
        stored = await redis.hgetall("forge:config")
        entries = []
        seen_keys = set()
        for item in CONFIG_KEYS:
            key = item["key"]
            seen_keys.add(key)
            value = stored.get(key) or os.environ.get(key, "")
            entries.append({
                "key": key,
                "value": value,
                "secret": item["secret"],
                "description": item["description"],
            })
        for key, value in sorted(stored.items()):
            if key not in seen_keys:
                entries.append({
                    "key": key,
                    "value": value,
                    "secret": False,
                    "description": "",
                })
        return entries


@router.put("/api/config")
async def api_config_update(body: ConfigUpdateRequest):
    async with redis_conn() as redis:
        updated = 0
        for entry in body.entries:
            key = entry.get("key")
            value = entry.get("value")
            if key and value is not None:
                await redis.hset("forge:config", key, value)
                updated += 1
        return {"ok": True, "updated": updated}
