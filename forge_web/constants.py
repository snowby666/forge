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
    {"key": "STITCH_API_KEY", "secret": True, "description": "Stitch API key"},
    {"key": "REDIS_URL", "secret": True, "description": "Redis connection URL"},
    {"key": "DATABASE_URL", "secret": True, "description": "PostgreSQL connection URL"},
]

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8081")
