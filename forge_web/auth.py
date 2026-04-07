"""Authentication middleware and helpers for the Forge web API."""

from __future__ import annotations

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse

from forge_web.constants import WEB_TOKEN


def extract_token(request: Request) -> str:
    """Extract the forge token from query params, cookies, or Authorization header."""
    return (
        request.query_params.get("token")
        or request.cookies.get("forge_token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or ""
    )


def extract_ws_token(websocket: WebSocket) -> str:
    """Extract the forge token from a WebSocket connection."""
    return (
        websocket.query_params.get("token", "")
        or websocket.cookies.get("forge_token", "")
        or websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )


def check_auth(request: Request) -> bool:
    if not WEB_TOKEN:
        return True
    return extract_token(request) == WEB_TOKEN


async def auth_middleware(request: Request, call_next):
    if request.url.path in ("/health",):
        return await call_next(request)
    if not check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)
