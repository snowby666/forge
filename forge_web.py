#!/usr/bin/env python3
"""
forge_web — API backend for the Forge dashboard.

Start:
    docker compose up -d web
    forge web
    uvicorn forge_web:app --host 0.0.0.0 --port 3000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.redis_client import get_redis

logger = logging.getLogger("forge.web")

app = FastAPI(title="Forge API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_TOKEN = os.environ.get("FORGE_WEB_TOKEN", "")

LAYER_AGENTS: dict[str, list[str]] = {
    "intelligence": ["hackathon_scout", "competitor_analyst", "judge_profiler", "sponsor_researcher"],
    "strategy": ["strategy_director", "pm", "tech_architect"],
    "design": ["ui_ux_designer"],
    "build": ["frontend_engineer", "backend_engineer", "integration_engineer", "test_engineer", "devops", "security"],
    "verify": ["code_reviewer", "ux_auditor", "performance"],
    "polish": ["polish", "copy_writer", "data_seeder", "brand"],
    "submission": ["demo_producer", "pitch_writer", "submission"],
    "infra": ["memory_keeper", "monitor", "calendar", "knowledge_updater", "outcome_tracker"],
}

_AGENT_TO_PHASE: dict[str, str] = {}
for _phase, _agents in LAYER_AGENTS.items():
    for _a in _agents:
        _AGENT_TO_PHASE[_a] = _phase

CHECKPOINT_LABELS = {
    "concept_approval": "Concept Approval",
    "design_approval": "Design Approval",
    "quality_review": "Quality Review",
    "submission_approval": "Submission Approval",
}

CONFIG_KEYS: list[dict[str, Any]] = [
    {"key": "ELECTRONHUB_API_KEY", "secret": True, "description": "ElectronHub LLM provider key"},
    {"key": "SERPER_API_KEY", "secret": True, "description": "Serper search API key"},
    {"key": "TAVILY_API_KEY", "secret": True, "description": "Tavily search API key"},
    {"key": "BRAVE_API_KEY", "secret": True, "description": "Brave search API key"},
    {"key": "EXA_API_KEY", "secret": True, "description": "Exa search API key"},
    {"key": "FIRECRAWL_API_KEY", "secret": True, "description": "Firecrawl scraping API key"},
    {"key": "STITCH_API_KEY", "secret": True, "description": "Stitch API key"},
    {"key": "REDIS_URL", "secret": True, "description": "Redis connection URL"},
    {"key": "DATABASE_URL", "secret": True, "description": "PostgreSQL connection URL"},
]


# ── Request models ────────────────────────────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    entries: list[dict[str, str]]


class BatchRequest(BaseModel):
    action: str
    ids: list[str]


# ── Auth middleware ───────────────────────────────────────────────────────────

def _check_auth(request: Request) -> bool:
    if not WEB_TOKEN:
        return True
    token = (
        request.query_params.get("token")
        or request.cookies.get("forge_token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    return token == WEB_TOKEN


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in ("/health",):
        return await call_next(request)
    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


# ── Exception handler ─────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled %s on %s: %s", type(exc).__name__, request.url.path, exc)
    return JSONResponse(
        {"error": type(exc).__name__, "detail": str(exc)},
        status_code=500,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _derive_phase(redis, hackathon_id: str) -> str:
    """Derive current phase from agent task statuses in Redis."""
    phase_order = ["intelligence", "strategy", "design", "build", "verify", "polish", "submission", "infra"]
    for phase_name in phase_order:
        agents = LAYER_AGENTS.get(phase_name, [])
        all_done = True
        for agent_id in agents:
            raw = await redis.get(f"task:{hackathon_id}:{agent_id}")
            if raw:
                try:
                    data = json.loads(raw)
                    if data.get("status") != "done":
                        all_done = False
                except Exception:
                    all_done = False
            else:
                all_done = False
        if not all_done:
            return phase_name
    return "submission"


async def _get_hackathons(redis) -> list[dict]:
    keys = await redis.keys("hackathon:*:brief")
    hacks = []
    for key in sorted(keys):
        hid = key.split(":")[1]
        brief_raw = await redis.get(key)
        brief = json.loads(brief_raw) if brief_raw else {}
        explicit = await redis.get(f"hackathon:{hid}:phase")
        if explicit and explicit != "unknown":
            phase = explicit
        else:
            phase = await _derive_phase(redis, hid)
        hacks.append({"id": hid, "brief": brief, "phase": phase})
    return hacks


async def _get_checkpoints(redis) -> list[dict]:
    keys = await redis.keys("checkpoint:*:*")
    checkpoints = []
    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) < 3:
            continue
        hid, cp_name = parts[1], parts[2]
        raw = await redis.get(key)
        is_pending = raw == "pending"
        data = {}
        if raw and raw != "pending":
            try:
                data = json.loads(raw)
            except Exception:
                pass
        checkpoints.append({
            "hackathon_id": hid,
            "checkpoint": cp_name,
            "pending": is_pending,
            "data": data,
        })
    return checkpoints


def _redact(value: str) -> str:
    if not value or len(value) <= 4:
        return "***"
    return value[:4] + "..."


async def _delete_hackathon(redis, hackathon_id: str) -> dict:
    brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
    if not brief_raw:
        return {"id": hackathon_id, "success": False, "error": "not found"}

    name = "?"
    try:
        name = json.loads(brief_raw).get("name", "?")
    except Exception:
        pass

    deleted = 0
    for pattern in [
        f"hackathon:{hackathon_id}:*",
        f"task:{hackathon_id}:*",
        f"checkpoint:{hackathon_id}:*",
        f"logs:{hackathon_id}",
    ]:
        keys = await redis.keys(pattern)
        if keys:
            deleted += await redis.delete(*keys)
    return {"id": hackathon_id, "success": True, "name": name, "keys_deleted": deleted}


async def _reroll_hackathon(redis, hackathon_id: str) -> dict:
    brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
    if not brief_raw:
        return {"id": hackathon_id, "success": False, "error": "not found"}

    name = json.loads(brief_raw).get("name", "?")
    agents_to_clear = [
        "strategy_director", "pm", "tech_architect", "ui_ux_designer",
        "frontend_engineer", "backend_engineer", "integration_engineer",
        "test_engineer", "devops", "security",
    ]
    checkpoints_to_clear = ["concept_approval", "design_approval", "quality_review"]

    cleared = 0
    for agent in agents_to_clear:
        key = f"task:{hackathon_id}:{agent}"
        if await redis.exists(key):
            await redis.delete(key)
            cleared += 1
    for cp in checkpoints_to_clear:
        key = f"checkpoint:{hackathon_id}:{cp}"
        if await redis.exists(key):
            await redis.delete(key)
            cleared += 1

    concepts_key = f"hackathon:{hackathon_id}:concepts"
    if await redis.exists(concepts_key):
        await redis.delete(concepts_key)
        cleared += 1

    return {"id": hackathon_id, "success": True, "name": name, "keys_cleared": cleared}


# ── Existing routes ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    checks: dict = {"redis": "fail"}
    try:
        redis = get_redis()
        try:
            pong = await redis.ping()
            checks["redis"] = "ok" if pong else "no_pong"
        finally:
            await redis.aclose()
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", **checks},
        status_code=200 if ok else 503,
    )


@app.get("/api/checkpoints")
async def api_checkpoints():
    redis = get_redis()
    try:
        return await _get_checkpoints(redis)
    finally:
        await redis.aclose()


@app.get("/api/hackathons")
async def api_hackathons():
    redis = get_redis()
    try:
        return await _get_hackathons(redis)
    finally:
        await redis.aclose()


@app.delete("/api/hackathon/{hackathon_id}")
async def api_delete_hackathon(hackathon_id: str):
    redis = get_redis()
    try:
        brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
        if not brief_raw:
            raise HTTPException(404, detail="Hackathon not found")

        name = "?"
        try:
            name = json.loads(brief_raw).get("name", "?")
        except Exception:
            pass

        deleted = 0
        for pattern in [
            f"hackathon:{hackathon_id}:*",
            f"task:{hackathon_id}:*",
            f"checkpoint:{hackathon_id}:*",
            f"logs:{hackathon_id}",
        ]:
            keys = await redis.keys(pattern)
            if keys:
                deleted += await redis.delete(*keys)

        return {"ok": True, "name": name, "keys_deleted": deleted}
    finally:
        await redis.aclose()


@app.post("/api/hackathon/{hackathon_id}/reroll")
async def api_reroll(hackathon_id: str):
    redis = get_redis()
    try:
        brief_raw = await redis.get(f"hackathon:{hackathon_id}:brief")
        if not brief_raw:
            raise HTTPException(404, detail="Hackathon not found")

        name = json.loads(brief_raw).get("name", "?")
        agents_to_clear = [
            "strategy_director", "pm", "tech_architect", "ui_ux_designer",
            "frontend_engineer", "backend_engineer", "integration_engineer",
            "test_engineer", "devops", "security",
        ]
        checkpoints_to_clear = ["concept_approval", "design_approval", "quality_review"]

        cleared = 0
        for agent in agents_to_clear:
            key = f"task:{hackathon_id}:{agent}"
            if await redis.exists(key):
                await redis.delete(key)
                cleared += 1
        for cp in checkpoints_to_clear:
            key = f"checkpoint:{hackathon_id}:{cp}"
            if await redis.exists(key):
                await redis.delete(key)
                cleared += 1

        concepts_key = f"hackathon:{hackathon_id}:concepts"
        if await redis.exists(concepts_key):
            await redis.delete(concepts_key)
            cleared += 1

        return {
            "ok": True,
            "name": name,
            "keys_cleared": cleared,
            "message": f"Cleared strategy/design state. Run: forge run --id {hackathon_id}",
        }
    finally:
        await redis.aclose()


@app.post("/api/approve/{hackathon_id}/{checkpoint}")
async def api_approve(hackathon_id: str, checkpoint: str, request: Request):
    redis = get_redis()
    try:
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
    finally:
        await redis.aclose()


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    if WEB_TOKEN:
        token = (
            websocket.query_params.get("token", "")
            or websocket.cookies.get("forge_token", "")
            or websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
        )
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


# ── Agent status ──────────────────────────────────────────────────────────────

@app.get("/api/hackathon/{hackathon_id}/agents")
async def api_agents(hackathon_id: str):
    redis = get_redis()
    try:
        keys = await redis.keys(f"task:{hackathon_id}:*")
        agents = []
        for key in sorted(keys):
            agent_id = key.split(":")[-1]
            raw = await redis.get(key)
            status = "unknown"
            phase = _AGENT_TO_PHASE.get(agent_id, "unknown")
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
            agents.append({
                "agent_id": agent_id,
                "status": status,
                "phase": phase,
                "elapsed": elapsed,
                "data": data,
            })
        return agents
    finally:
        await redis.aclose()


# ── Trigger / restart agents ──────────────────────────────────────────────────

@app.post("/api/hackathon/{hackathon_id}/agent/{agent_id}/trigger")
async def api_trigger_agent(hackathon_id: str, agent_id: str):
    redis = get_redis()
    try:
        await redis.publish("agent:trigger", json.dumps({
            "hackathon_id": hackathon_id,
            "agent": agent_id,
            "input": {},
        }))
        return {"ok": True}
    finally:
        await redis.aclose()


@app.post("/api/hackathon/{hackathon_id}/agent/{agent_id}/restart")
async def api_restart_agent(hackathon_id: str, agent_id: str):
    redis = get_redis()
    try:
        await redis.delete(f"task:{hackathon_id}:{agent_id}")
        await redis.publish("agent:trigger", json.dumps({
            "hackathon_id": hackathon_id,
            "agent": agent_id,
            "input": {},
        }))
        return {"ok": True}
    finally:
        await redis.aclose()


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/api/hackathon/{hackathon_id}/logs")
async def api_logs(
    hackathon_id: str,
    agent: str | None = Query(None),
    level: str | None = Query(None),
):
    redis = get_redis()
    try:
        raw_entries = await redis.lrange(f"logs:{hackathon_id}", -500, -1)
        logs = []
        for entry in raw_entries:
            try:
                parsed = json.loads(entry)
            except Exception:
                continue
            if agent and parsed.get("agent_id") != agent:
                continue
            if level and parsed.get("level") != level:
                continue
            logs.append(parsed)
        return logs
    finally:
        await redis.aclose()


# ── Analytics ─────────────────────────────────────────────────────────────────

async def _build_analytics(redis, hackathon_filter: str | None = None) -> dict:
    if hackathon_filter:
        brief_keys = [f"hackathon:{hackathon_filter}:brief"]
    else:
        brief_keys = sorted(await redis.keys("hackathon:*:brief"))

    cost_by_hackathon = []
    daily_runs: dict[str, int] = {}
    for bk in brief_keys:
        raw = await redis.get(bk)
        if not raw:
            continue
        try:
            brief = json.loads(raw)
        except Exception:
            continue
        hid = bk.split(":")[1]
        cost = brief.get("cost_usd") or brief.get("total_cost") or 0
        cost_by_hackathon.append({"name": brief.get("name", hid), "cost_usd": cost})
        created = brief.get("created_at") or brief.get("started_at") or ""
        if created:
            day = created[:10]
            daily_runs[day] = daily_runs.get(day, 0) + 1

    if hackathon_filter:
        task_keys = sorted(await redis.keys(f"task:{hackathon_filter}:*"))
    else:
        task_keys = sorted(await redis.keys("task:*:*"))

    agent_times: dict[str, list[float]] = {}
    agent_success: dict[str, dict[str, int]] = {}
    for tk in task_keys:
        agent_id = tk.split(":")[-1]
        raw = await redis.get(tk)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue

        status = parsed.get("status", "")
        if agent_id not in agent_success:
            agent_success[agent_id] = {"success": 0, "total": 0}
        agent_success[agent_id]["total"] += 1
        if status == "done":
            agent_success[agent_id]["success"] += 1

        started = parsed.get("started_at")
        finished = parsed.get("finished_at")
        if started and finished:
            try:
                dt = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
                agent_times.setdefault(agent_id, []).append(dt)
            except Exception:
                pass

    agent_timing = []
    for aid, times in sorted(agent_times.items()):
        agent_timing.append({"agent_id": aid, "avg_seconds": round(sum(times) / len(times), 1)})

    success_rates = []
    for aid, counts in sorted(agent_success.items()):
        total = counts["total"]
        pct = round(counts["success"] / total * 100, 1) if total else 0
        success_rates.append({"agent_id": aid, "success_pct": pct, "total_runs": total})

    daily_list = [{"date": d, "count": c} for d, c in sorted(daily_runs.items())]

    return {
        "cost_by_hackathon": cost_by_hackathon,
        "agent_timing": agent_timing,
        "success_rates": success_rates,
        "daily_runs": daily_list,
    }


@app.get("/api/analytics")
async def api_analytics():
    redis = get_redis()
    try:
        return await _build_analytics(redis)
    finally:
        await redis.aclose()


@app.get("/api/analytics/{hackathon_id}")
async def api_analytics_hackathon(hackathon_id: str):
    redis = get_redis()
    try:
        return await _build_analytics(redis, hackathon_filter=hackathon_id)
    finally:
        await redis.aclose()


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config_read():
    redis = get_redis()
    try:
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
    finally:
        await redis.aclose()


@app.put("/api/config")
async def api_config_update(body: ConfigUpdateRequest):
    redis = get_redis()
    try:
        updated = 0
        for entry in body.entries:
            key = entry.get("key")
            value = entry.get("value")
            if key and value is not None:
                await redis.hset("forge:config", key, value)
                updated += 1
        return {"ok": True, "updated": updated}
    finally:
        await redis.aclose()


# ── Design / artifacts ────────────────────────────────────────────────────────

@app.get("/api/hackathon/{hackathon_id}/design")
async def api_design(hackathon_id: str):
    redis = get_redis()
    try:
        raw = await redis.get(f"hackathon:{hackathon_id}:design_spec")
        if raw:
            try:
                data = json.loads(raw)
                return {
                    "design_md": data.get("design_md", data.get("markdown", "")),
                    "screenshots": data.get("screenshots", []),
                    "tokens": data.get("tokens") or {},
                    "components": data.get("components", []),
                    "screens": data.get("screens", []),
                    "personality": data.get("personality"),
                    "critique": data.get("critique") or data.get("self_critique"),
                    "figma_file_id": data.get("figma_file_id"),
                }
            except Exception:
                return {"design_md": raw, "screenshots": [], "tokens": {}, "components": [], "screens": [], "personality": None, "critique": None, "figma_file_id": None}

        task_raw = await redis.get(f"task:{hackathon_id}:ui_ux_designer")
        if not task_raw:
            return {"design_md": "", "screenshots": [], "tokens": {}, "components": [], "screens": [], "personality": None, "critique": None, "figma_file_id": None}

        try:
            task = json.loads(task_raw)
        except Exception:
            return {"design_md": "", "screenshots": [], "tokens": {}, "components": [], "screens": [], "personality": None, "critique": None, "figma_file_id": None}

        data = task.get("data") or {}

        design_md = ""
        md_path = data.get("design_md_path")
        if md_path and os.path.isfile(md_path):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    design_md = f.read()
            except Exception:
                pass
        if not design_md:
            spec = data.get("design_spec") or {}
            parts = []
            if spec.get("app_name"):
                parts.append(f"# {spec['app_name']}")
            if spec.get("description"):
                parts.append(spec["description"])
            for screen in spec.get("screens", []):
                parts.append(f"## {screen.get('name', 'Screen')}")
                if screen.get("purpose"):
                    parts.append(screen["purpose"])
            design_md = "\n\n".join(parts)

        screenshots = []
        for ss in data.get("stitch_screens", []):
            if ss.get("image_url"):
                screenshots.append(ss["image_url"])
        spec = data.get("design_spec") or {}
        for screen in spec.get("screens", []):
            if screen.get("image_url"):
                screenshots.append(screen["image_url"])

        tokens = data.get("tokens") or {}

        components = []
        for comp in (spec.get("components") or []):
            components.append({
                "name": comp.get("name", ""),
                "description": comp.get("description", ""),
                "is_demo_critical": comp.get("is_demo_critical", False),
                "file_path": comp.get("file_path", ""),
                "shadcn_base": comp.get("shadcn_base", ""),
                "purpose": comp.get("purpose", ""),
            })

        screens = []
        for scr in (spec.get("screens") or []):
            screens.append({
                "route": scr.get("route", ""),
                "name": scr.get("name", ""),
                "purpose": scr.get("purpose", ""),
                "primary_action": scr.get("primary_action", ""),
            })

        return {
            "design_md": design_md,
            "screenshots": screenshots,
            "tokens": tokens,
            "components": components,
            "screens": screens,
            "personality": data.get("personality"),
            "critique": data.get("self_critique") or data.get("critique"),
            "figma_file_id": data.get("figma_file_id"),
        }
    finally:
        await redis.aclose()


@app.get("/api/hackathon/{hackathon_id}/artifacts")
async def api_artifacts(hackathon_id: str):
    redis = get_redis()
    try:
        keys = await redis.keys(f"hackathon:{hackathon_id}:*")
        artifacts = []
        for key in sorted(keys):
            if key.endswith(":brief"):
                continue
            raw = await redis.get(key)
            data: Any = None
            if raw:
                try:
                    data = json.loads(raw)
                except Exception:
                    data = raw
            artifacts.append({"key": key, "data": data})
        return artifacts
    finally:
        await redis.aclose()


# ── Batch operations ──────────────────────────────────────────────────────────

@app.post("/api/hackathon/batch")
async def api_batch(body: BatchRequest):
    if body.action not in ("delete", "reroll"):
        raise HTTPException(400, detail=f"Unknown action: {body.action}")

    redis = get_redis()
    try:
        results = []
        for hid in body.ids:
            try:
                if body.action == "delete":
                    result = await _delete_hackathon(redis, hid)
                else:
                    result = await _reroll_hackathon(redis, hid)
                results.append(result)
            except Exception as exc:
                results.append({"id": hid, "success": False, "error": str(exc)})
        return {"ok": True, "results": results}
    finally:
        await redis.aclose()


# ── CLI features ──────────────────────────────────────────────────────────────

@app.post("/api/scout")
async def api_run_scout(body: dict = {}):
    dry_run = body.get("dry_run", False)
    cmd = [sys.executable, "-m", "forge", "scout"]
    if dry_run:
        cmd.append("--dry-run")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    return {"ok": True, "pid": proc.pid, "message": "Scout started in background"}


@app.post("/api/hackathon/{hackathon_id}/run")
async def api_run_hackathon(hackathon_id: str, body: dict = {}):
    from_phase = body.get("from_phase")
    restart = body.get("restart", False)
    cmd = [sys.executable, "-m", "forge", "run", "--id", hackathon_id]
    if restart:
        cmd.append("--restart")
    if from_phase:
        cmd.extend(["--from-phase", from_phase])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    return {"ok": True, "pid": proc.pid}


@app.post("/api/test")
async def api_test():
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "forge", "test",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        return {"ok": proc.returncode == 0, "stdout": stdout.decode(), "stderr": stderr.decode()}
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "stdout": "", "stderr": "Test timed out after 60s"}


# ── Services health ───────────────────────────────────────────────────────────

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8081")


@app.get("/api/services/health")
async def api_services_health():
    import urllib.request

    services = []

    t0 = time.monotonic()
    try:
        redis = get_redis()
        try:
            await redis.ping()
            services.append({"name": "redis", "status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)})
        finally:
            await redis.aclose()
    except Exception as exc:
        services.append({"name": "redis", "status": "error", "error": str(exc)})

    async def _check_http(name: str, url: str, headers: dict[str, str] | None = None):
        t = time.monotonic()
        try:
            loop = asyncio.get_event_loop()
            req = urllib.request.Request(url, method="GET")
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=5)),
                timeout=6,
            )
            latency = round((time.monotonic() - t) * 1000, 1)
            return {"name": name, "status": "ok", "latency_ms": latency}
        except Exception as exc:
            return {"name": name, "status": "error", "error": str(exc)}

    qdrant_api_key = os.environ.get("QDRANT_API_KEY", "")
    qdrant_headers = {"api-key": qdrant_api_key} if qdrant_api_key else None
    qdrant_check, searxng_check = await asyncio.gather(
        _check_http("qdrant", f"{QDRANT_URL}/readyz", headers=qdrant_headers),
        _check_http("searxng", f"{SEARXNG_URL}/healthz"),
    )
    services.append(qdrant_check)
    services.append(searxng_check)

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        t1 = time.monotonic()
        try:
            from urllib.parse import urlparse
            parsed = urlparse(db_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5,
            )
            writer.close()
            await writer.wait_closed()
            latency = round((time.monotonic() - t1) * 1000, 1)
            services.append({"name": "postgresql", "status": "ok", "latency_ms": latency})
        except Exception as exc:
            services.append({"name": "postgresql", "status": "error", "error": str(exc)})
    else:
        services.append({"name": "postgresql", "status": "error", "error": "DATABASE_URL not set"})

    return {"services": services}


# ── Standalone run ────────────────────────────────────────────────────────────

def start(host: str = "0.0.0.0", port: int = 3001):
    import uvicorn
    uvicorn.run("forge_web:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=3001)
    args = p.parse_args()
    start(args.host, args.port)
