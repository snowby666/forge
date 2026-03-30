"""
ElectronHub API client — single source of truth for all LLM calls.
Base URL: https://api.electronhub.ai/v1 (OpenAI-compatible)

NEVER instantiate AsyncOpenAI directly in agent code.
ALWAYS import complete(), complete_json(), or embed() from here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from enum import Enum
from typing import Any, Type, TypeVar

from openai import AsyncOpenAI, APIStatusError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Singleton client ──────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        key = os.environ.get("ELECTRONHUB_API_KEY")
        if not key:
            raise RuntimeError("ELECTRONHUB_API_KEY not set")
        _client = AsyncOpenAI(
            api_key=key,
            base_url=os.environ.get("ELECTRONHUB_BASE_URL", "https://api.electronhub.ai/v1"),
        )
    return _client


# ── Model tiers ───────────────────────────────────────────────────────────────

class Tier(str, Enum):
    HEAVY    = "heavy"     # architecture, hard debugging — Opus
    STANDARD = "standard"  # most agent work — Sonnet
    BULK     = "bulk"      # tests, lint, boilerplate — gpt-4o-mini
    FAST     = "fast"      # classification, browser actions — Haiku
    VISION   = "vision"    # image/design analysis — gemini-2.0-flash
    WRITING  = "writing"   # README, pitch copy, demo scripts — gpt-4o
    DESIGN   = "design"    # UI aesthetic reasoning — claude-sonnet (high temp)


MODELS: dict[Tier, str] = {
    Tier.HEAVY:    "claude-opus-4-5",
    Tier.STANDARD: "claude-sonnet-4-5",
    Tier.BULK:     "gpt-4o-mini",
    Tier.FAST:     "claude-haiku-4-5",
    Tier.VISION:   "gemini-2.0-flash",
    Tier.WRITING:  "gpt-4o",
    Tier.DESIGN:   "claude-sonnet-4-5",   # same model, higher temperature
}

MAX_TOKENS: dict[Tier, int] = {
    Tier.HEAVY:    8192,
    Tier.STANDARD: 4096,
    Tier.BULK:     2048,
    Tier.FAST:      512,
    Tier.VISION:   4096,
    Tier.WRITING:  4096,
    Tier.DESIGN:   4096,
}

DEFAULT_TEMP: dict[Tier, float] = {
    Tier.HEAVY:    0.1,
    Tier.STANDARD: 0.2,
    Tier.BULK:     0.0,
    Tier.FAST:     0.0,
    Tier.VISION:   0.2,
    Tier.WRITING:  0.4,
    Tier.DESIGN:   0.7,   # higher creativity for design work
}

FALLBACK: dict[str, str] = {
    "claude-opus-4-5":   "claude-sonnet-4-5",
    "claude-sonnet-4-5": "gpt-4o",
    "gpt-4o":            "gpt-4o-mini",
    "gpt-4o-mini":       "claude-haiku-4-5",
    "gemini-2.0-flash":  "claude-sonnet-4-5",
}


# ── Task → tier routing ───────────────────────────────────────────────────────

TASK_TIER: dict[str, Tier] = {
    # Intelligence layer
    "scout-hackathons":         Tier.FAST,
    "score-hackathon":          Tier.FAST,
    "analyze-competitors":      Tier.STANDARD,
    "profile-judges":           Tier.STANDARD,
    "research-sponsor-apis":    Tier.STANDARD,

    # Strategy layer
    "generate-concepts":        Tier.STANDARD,
    "write-user-stories":       Tier.STANDARD,
    "create-sprint-plan":       Tier.STANDARD,
    "design-api-contract":      Tier.STANDARD,
    "design-db-schema":         Tier.STANDARD,
    "debug-architecture":       Tier.HEAVY,

    # Design layer — THE MOST IMPORTANT
    "design-system-create":     Tier.DESIGN,
    "generate-color-palette":   Tier.DESIGN,
    "write-component-spec":     Tier.DESIGN,
    "critique-design":          Tier.DESIGN,
    "generate-design-tokens":   Tier.DESIGN,
    "write-ux-copy":            Tier.WRITING,
    "audit-visual-hierarchy":   Tier.VISION,
    "generate-brand-identity":  Tier.DESIGN,

    # Build layer
    "generate-component":       Tier.STANDARD,
    "generate-page":            Tier.STANDARD,
    "generate-api-route":       Tier.STANDARD,
    "fix-typescript-error":     Tier.STANDARD,
    "fix-lint-error":           Tier.BULK,
    "write-tests":              Tier.BULK,
    "write-pytest":             Tier.BULK,
    "integrate-sponsor-api":    Tier.STANDARD,
    "write-migrations":         Tier.STANDARD,
    "fix-python-error":         Tier.STANDARD,

    # Verify layer
    "review-code":              Tier.STANDARD,
    "audit-ux-flow":            Tier.DESIGN,
    "check-accessibility":      Tier.STANDARD,
    "run-lighthouse-analysis":  Tier.FAST,
    "security-scan":            Tier.STANDARD,

    # Polish layer
    "polish-animations":        Tier.STANDARD,
    "rewrite-ux-copy":          Tier.WRITING,
    "seed-demo-data":           Tier.BULK,
    "generate-logo":            Tier.DESIGN,
    "generate-og-image":        Tier.DESIGN,

    # Submission layer
    "write-demo-script":        Tier.WRITING,
    "write-readme":             Tier.WRITING,
    "write-pitch-deck":         Tier.WRITING,
    "write-submission-copy":    Tier.WRITING,

    # Browser layer
    "browser-act":              Tier.FAST,
    "browser-extract":          Tier.FAST,
}


def resolve(task: str) -> tuple[str, Tier]:
    tier = TASK_TIER.get(task, Tier.STANDARD)
    return MODELS[tier], tier


# ── Core helpers ──────────────────────────────────────────────────────────────

Message = dict[str, str]
T = TypeVar("T", bound=BaseModel)


async def complete(
    *,
    task: str,
    messages: list[Message],
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_retries: int = 3,
) -> str:
    model, tier = resolve(task)
    temp = temperature if temperature is not None else DEFAULT_TEMP[tier]
    max_tokens = MAX_TOKENS[tier]

    full_messages: list[Message] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    client = get_client()
    current_model = model

    for attempt in range(max_retries):
        try:
            resp = await client.chat.completions.create(
                model=current_model,
                messages=full_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temp,
            )
            return resp.choices[0].message.content or ""
        except APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 504):
                fb = FALLBACK.get(current_model)
                if fb:
                    logger.warning(f"[forge:llm] {e.status_code} → fallback {current_model}→{fb}")
                    current_model = fb
                    await asyncio.sleep(2 ** attempt)
                    continue
            raise

    raise RuntimeError(f"[forge:llm] exhausted retries for task={task}")


async def complete_json(
    *,
    task: str,
    messages: list[Message],
    response_model: Type[T],
    system_prompt: str | None = None,
    temperature: float | None = None,
) -> T:
    schema = json.dumps(response_model.model_json_schema(), indent=2)
    sys = (system_prompt or "") + f"\n\nRespond ONLY with valid JSON matching:\n{schema}"
    raw = await complete(task=task, messages=messages, system_prompt=sys, temperature=temperature)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return response_model.model_validate(json.loads(cleaned))


async def embed(text: str) -> list[float]:
    resp = await get_client().embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


async def complete_batch(
    tasks: list[dict[str, Any]],
    concurrency: int = 5,
) -> list[str]:
    sem = asyncio.Semaphore(concurrency)
    async def _run(item: dict[str, Any]) -> str:
        async with sem:
            return await complete(**item)
    return list(await asyncio.gather(*[_run(t) for t in tasks]))
