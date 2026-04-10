"""Shared constants for the Forge web API."""

from __future__ import annotations

import os
from typing import Any

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

AGENT_TO_PHASE: dict[str, str] = {}
for _phase, _agents in LAYER_AGENTS.items():
    for _a in _agents:
        AGENT_TO_PHASE[_a] = _phase

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
    {"key": "GOOGLE_STITCH_TOKENS", "secret": True, "description": "Google Stitch tokens (comma-separated for rotation)"},
    {"key": "REDIS_URL", "secret": True, "description": "Redis connection URL"},
    {"key": "DATABASE_URL", "secret": True, "description": "PostgreSQL connection URL"},
]

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8081")

# ── Service Registry ─────────────────────────────────────────────────────────
# Single source of truth for all microservice URLs, ports, and health endpoints.
# Docker-internal URLs are resolved from compose `environment:` overrides;
# these defaults are for host-side / CLI usage.

SERVICE_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "redis",
        "description": "Working memory, pub/sub, task statuses",
        "host_port": 6379,
        "docker_host": "redis",
        "type": "docker",
        "category": "core",
        "check": "tcp",
    },
    {
        "name": "postgresql",
        "description": "LangGraph state, app database, n8n config",
        "host_port": 5432,
        "docker_host": "postgres",
        "type": "docker",
        "category": "core",
        "check": "tcp",
    },
    {
        "name": "qdrant",
        "description": "Vector store — 5 collections, 1536-dim embeddings",
        "host_port": 6333,
        "docker_host": "qdrant",
        "url": os.environ.get("QDRANT_URL", "http://localhost:6333"),
        "type": "docker",
        "category": "core",
        "check": "http",
        "health_path": "/readyz",
        "auth_header": "api-key",
        "auth_env": "QDRANT_API_KEY",
    },
    {
        "name": "searxng",
        "description": "Self-hosted metasearch engine (ForgeSearch)",
        "host_port": 8081,
        "docker_host": "searxng",
        "docker_port": 8080,
        "url": os.environ.get("SEARXNG_URL", "http://localhost:8081"),
        "type": "docker",
        "category": "core",
        "check": "http",
        "health_path": "/healthz",
    },
    {
        "name": "temporal",
        "description": "Durable workflow execution, crash recovery",
        "host_port": 7233,
        "docker_host": "temporal",
        "type": "docker",
        "category": "core",
        "check": "tcp",
    },
    {
        "name": "temporal-ui",
        "description": "Temporal workflow inspection dashboard",
        "host_port": 8080,
        "docker_host": "temporal-ui",
        "url": "http://localhost:8080",
        "type": "docker",
        "category": "ui",
        "check": "http",
        "health_path": "/",
    },
    {
        "name": "n8n",
        "description": "Workflow automation, human checkpoint webhooks",
        "host_port": 5678,
        "docker_host": "n8n",
        "url": "http://localhost:5678",
        "type": "docker",
        "category": "automation",
        "check": "http",
        "health_path": "/healthz",
    },
    {
        "name": "daytona",
        "description": "Isolated code sandbox server for build agents",
        "host_port": 3986,
        "docker_host": "daytona-api",
        "docker_port": 3000,
        "url": os.environ.get("DAYTONA_API_URL", "http://localhost:3986"),
        "type": "docker",
        "category": "build",
        "check": "http",
        "health_path": "/health",
    },
    {
        "name": "browser",
        "description": "Stagehand + Playwright — scraping, screenshots, demos",
        "host_port": 3100,
        "docker_host": "browser",
        "docker_port": 3100,
        "url": os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100"),
        "type": "docker",
        "category": "automation",
        "check": "http",
        "health_path": "/health",
    },
    {
        "name": "forge-api",
        "description": "FastAPI backend — dashboard REST + WebSocket",
        "host_port": 3001,
        "docker_host": "api",
        "type": "docker",
        "category": "ui",
        "check": "http",
        "health_path": "/health",
        "url": "http://localhost:3001",
    },
    {
        "name": "forge-web",
        "description": "Next.js 15 dashboard frontend (sentinelhive.dev)",
        "host_port": 3000,
        "docker_host": "web",
        "type": "docker",
        "category": "ui",
        "check": "http",
        "health_path": "/",
        "url": "http://localhost:3000",
    },
    {
        "name": "vercel",
        "description": "Frontend deployment target (external)",
        "url": "https://api.vercel.com",
        "type": "external",
        "category": "deploy",
        "check": "http",
        "health_path": "/v2",
        "auth_header": "Authorization",
        "auth_env": "VERCEL_TOKEN",
    },
    {
        "name": "railway",
        "description": "Backend deployment target (external)",
        "url": "https://backboard.railway.com",
        "type": "external",
        "category": "deploy",
        "check": "http",
        "health_path": "/graphql/v2",
        "auth_header": "Authorization",
        "auth_env": "RAILWAY_TOKEN",
    },
]
