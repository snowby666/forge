"""WebSocket endpoint for real-time agent updates."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.redis_client import get_redis
from forge_web.auth import extract_ws_token
from forge_web.constants import WEB_TOKEN

router = APIRouter()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    if WEB_TOKEN:
        token = extract_ws_token(websocket)
        if token != WEB_TOKEN:
            await websocket.close(code=4001, reason="unauthorized")
            return
    await websocket.accept()
    redis = get_redis()
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe("forge:agent_updates")
        last_snapshot: dict[str, str] = {}

        async def _relay_pubsub():
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg and msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        await websocket.send_json(data)
                    except Exception:
                        await websocket.send_json({"type": "raw", "data": str(msg["data"])})
                await asyncio.sleep(0.05)

        async def _poll_tasks():
            nonlocal last_snapshot
            while True:
                try:
                    poll_redis = get_redis()
                    try:
                        keys = await poll_redis.keys("task:*:*")
                        current: dict[str, str] = {}
                        for k in keys:
                            raw = await poll_redis.get(k)
                            current[k] = raw or ""

                        for k, v in current.items():
                            if k not in last_snapshot or last_snapshot[k] != v:
                                parts = k.split(":")
                                if len(parts) >= 3:
                                    hid, agent_id = parts[1], parts[2]
                                    status = "unknown"
                                    data = None
                                    try:
                                        parsed = json.loads(v)
                                        status = parsed.get("status", "unknown")
                                        data = parsed
                                    except Exception:
                                        status = v if v else "unknown"
                                    await websocket.send_json({
                                        "type": "agent_status",
                                        "hackathon_id": hid,
                                        "agent_id": agent_id,
                                        "status": status,
                                        "data": data,
                                    })
                        last_snapshot = current
                    finally:
                        await poll_redis.aclose()
                except WebSocketDisconnect:
                    raise
                except Exception:
                    pass
                await asyncio.sleep(2)

        await asyncio.gather(_relay_pubsub(), _poll_tasks())
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await pubsub.unsubscribe("forge:agent_updates")
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await redis.aclose()
        except Exception:
            pass
