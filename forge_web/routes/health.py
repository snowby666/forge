"""Health check endpoints."""

from __future__ import annotations

import asyncio
import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config.redis_client import get_redis
from forge_web.constants import QDRANT_URL, SEARXNG_URL

router = APIRouter()


@router.get("/health")
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


@router.get("/api/services/health")
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
