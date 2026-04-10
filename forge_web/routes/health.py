"""Health check endpoints."""

from __future__ import annotations

import asyncio
import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config.redis_client import get_redis
from forge_web.constants import SERVICE_REGISTRY

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


async def _check_redis() -> dict:
    t0 = time.monotonic()
    try:
        redis = get_redis()
        try:
            await redis.ping()
            return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
        finally:
            await redis.aclose()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_tcp(host: str, port: int) -> dict:
    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5,
        )
        writer.close()
        await writer.wait_closed()
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_http(url: str, headers: dict[str, str] | None = None) -> dict:
    import urllib.request

    t0 = time.monotonic()
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
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _resolve_url(svc: dict) -> str:
    """Build the health check URL for a service, preferring Docker-internal names."""
    if "url" in svc:
        docker_host = svc.get("docker_host", "")
        docker_port = svc.get("docker_port", svc.get("host_port"))
        is_docker = os.environ.get("DOCKER_CONTAINER") or os.path.exists("/.dockerenv")
        if is_docker and docker_host:
            # For host-gateway services (e.g. browser layer), resolve the actual
            # gateway IP since host.docker.internal DNS can be flaky on WSL2.
            if docker_host == "host.docker.internal":
                gateway_ip = _get_host_gateway_ip()
                if gateway_ip:
                    return f"http://{gateway_ip}:{docker_port}"
            return f"http://{docker_host}:{docker_port}"
        return svc["url"]
    return ""


def _get_host_gateway_ip() -> str:
    """Read the gateway IP from /etc/hosts (set by Docker's extra_hosts: host-gateway)."""
    try:
        with open("/etc/hosts") as f:
            for line in f:
                line = line.strip()
                if "host.docker.internal" in line and not line.startswith("#"):
                    return line.split()[0]
    except FileNotFoundError:
        pass
    # Fallback: try resolving it via DNS
    try:
        import socket
        return socket.gethostbyname("host.docker.internal")
    except Exception:
        pass
    return ""


@router.get("/api/services/health")
async def api_services_health():
    tasks = []
    service_meta = []

    for svc in SERVICE_REGISTRY:
        name = svc["name"]
        check_type = svc.get("check", "tcp")
        meta = {
            "name": name,
            "description": svc.get("description", ""),
            "port": svc.get("host_port"),
            "type": svc.get("type", "docker"),
            "category": svc.get("category", "core"),
        }
        service_meta.append(meta)

        if name == "redis":
            tasks.append(_check_redis())
        elif check_type == "tcp":
            host = svc.get("docker_host", "localhost")
            port = svc.get("docker_port", svc.get("host_port", 0))
            is_docker = os.path.exists("/.dockerenv")
            if is_docker and host:
                tasks.append(_check_tcp(host, port))
            else:
                from urllib.parse import urlparse
                db_url = os.environ.get("DATABASE_URL", "")
                if name == "postgresql" and db_url:
                    parsed = urlparse(db_url)
                    tasks.append(_check_tcp(parsed.hostname or "localhost", parsed.port or 5432))
                else:
                    tasks.append(_check_tcp("localhost", svc.get("host_port", 0)))
        elif check_type == "http":
            base_url = _resolve_url(svc)
            health_path = svc.get("health_path", "/health")
            url = f"{base_url.rstrip('/')}{health_path}"

            headers = None
            auth_env = svc.get("auth_env")
            auth_header = svc.get("auth_header")
            if auth_env and auth_header:
                key = os.environ.get(auth_env, "")
                if key:
                    headers = {auth_header: key}

            tasks.append(_check_http(url, headers=headers))
        else:
            async def _skip():
                return {"status": "error", "error": "unknown check type"}
            tasks.append(_skip())

    results = await asyncio.gather(*tasks, return_exceptions=True)

    services = []
    for meta, result in zip(service_meta, results):
        if isinstance(result, Exception):
            entry = {**meta, "status": "error", "error": str(result)}
        else:
            entry = {**meta, **result}
        services.append(entry)

    return {"services": services}
