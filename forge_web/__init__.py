"""
forge_web — API backend for the Forge dashboard.

Usage:
    uvicorn forge_web:app --host 0.0.0.0 --port 3001
    python -m forge_web
    forge web
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from forge_web.auth import auth_middleware as _auth_mw
from forge_web.routes import (
    health,
    hackathons,
    checkpoints,
    agents,
    analytics,
    config,
    design,
    batch,
    cli,
    ws,
    traces,
)

logger = logging.getLogger("forge.web")


def create_app() -> FastAPI:
    application = FastAPI(title="Forge API", docs_url=None, redoc_url=None)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.middleware("http")(_auth_mw)

    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled %s on %s: %s", type(exc).__name__, request.url.path, exc)
        return JSONResponse(
            {"error": type(exc).__name__, "detail": str(exc)},
            status_code=500,
        )

    application.include_router(health.router)
    application.include_router(hackathons.router)
    application.include_router(checkpoints.router)
    application.include_router(agents.router)
    application.include_router(analytics.router)
    application.include_router(config.router)
    application.include_router(design.router)
    application.include_router(batch.router)
    application.include_router(cli.router)
    application.include_router(ws.router)
    application.include_router(traces.router)

    return application


app = create_app()
