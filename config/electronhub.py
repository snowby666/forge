# -*- coding: utf-8 -*-
"""
ElectronHub API client — single source of truth for all LLM calls.
Base URL: https://api.electronhub.ai/v1 (OpenAI-compatible)

NEVER instantiate AsyncOpenAI directly in agent code.
ALWAYS import complete(), complete_json(), or embed() from here.

Model overrides — set any of these in .env or forge.secrets:
  FORGE_MODEL_HEAVY    default: claude-opus-4-6
  FORGE_MODEL_STANDARD default: claude-sonnet-4-6
  FORGE_MODEL_DESIGN   default: claude-sonnet-4-6
  FORGE_MODEL_WRITING  default: gpt-4.1
  FORGE_MODEL_BULK     default: gpt-4.1-mini
  FORGE_MODEL_FAST     default: gpt-5-nano
  FORGE_MODEL_VISION   default: claude-sonnet-4-6  (vision-capable)

Max token overrides per tier:
  FORGE_MAX_TOKENS_HEAVY    default: 64000
  FORGE_MAX_TOKENS_STANDARD default: 32000
  FORGE_MAX_TOKENS_DESIGN   default: 32000
  FORGE_MAX_TOKENS_WRITING  default: 16000
  FORGE_MAX_TOKENS_BULK     default: 8000
  FORGE_MAX_TOKENS_FAST     default: 4000
  FORGE_MAX_TOKENS_VISION   default: 16000

Models as of 2026-03-31 (from https://api.electronhub.ai/v1/models):
  claude-opus-4-6    Anthropic flagship; 80.8% SWE-bench; 128k output; $5/$25 /MTok
  claude-sonnet-4-6  Balanced SOTA; 79.6% SWE-bench; 64k output; $3/$15 /MTok
  claude-haiku-4-5   Fast Claude; sub-second; $0.25/$1.25 /MTok
  gpt-4.1            OpenAI flagship; 54.6% SWE-bench; 1M ctx; $2/$8 /MTok
  gpt-4.1-mini       Balanced OpenAI; 1M ctx; $0.40/$1.60 /MTok
  gpt-4.1-nano       Ultra-cheap OpenAI; 1M ctx; $0.10/$0.40 /MTok
  gpt-5-nano         GPT-5 micro; 400k ctx; $0.05/$0.40 /MTok
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Type, TypeVar

from openai import AsyncOpenAI, APIStatusError
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Secrets file loader ───────────────────────────────────────────────────────
# forge.secrets is gitignored. It holds model overrides and API keys.
# env vars take precedence; secrets file fills in the rest.

def _load_secrets() -> None:
    secrets_file = Path(os.path.dirname(__file__)).parent / "forge.secrets"
    if not secrets_file.exists():
        return
    try:
        for line in secrets_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as e:
        logger.debug(f"[forge:llm] Could not load forge.secrets: {e}")

_load_secrets()


# ── Singleton client ──────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        key = os.environ.get("ELECTRONHUB_API_KEY")
        if not key:
            raise RuntimeError(
                "ELECTRONHUB_API_KEY not set. "
                "Add it to .env or forge.secrets: ELECTRONHUB_API_KEY=your_key"
            )
        _client = AsyncOpenAI(
            api_key=key,
            base_url=os.environ.get("ELECTRONHUB_BASE_URL", "https://api.electronhub.ai/v1"),
        )
    return _client


# ── Model tiers ───────────────────────────────────────────────────────────────

class Tier(str, Enum):
    HEAVY    = "heavy"    # Architecture, complex reasoning — Opus 4.6
    STANDARD = "standard" # Most agent work — Sonnet 4.6
    DESIGN   = "design"   # UI aesthetic reasoning — Sonnet 4.6 high temp
    WRITING  = "writing"  # README, pitch copy, scripts — GPT-4.1
    BULK     = "bulk"     # Tests, lint, boilerplate — GPT-4.1-mini
    FAST     = "fast"     # Classification, scoring — GPT-5-nano
    VISION   = "vision"   # Screenshot/design analysis — Sonnet 4.6


# ── SOTA defaults (March 2026) ────────────────────────────────────────────────

_DEFAULT_MODELS: dict[Tier, str] = {
    Tier.HEAVY:    "claude-opus-4-6",    # 80.8% SWE-bench, best reasoning
    Tier.STANDARD: "claude-sonnet-4-6",  # 79.6% SWE-bench, best value Claude
    Tier.DESIGN:   "claude-sonnet-4-6",  # Vision + aesthetic sense
    Tier.WRITING:  "gpt-4.1",            # Strong instruction following, $2/$8
    Tier.BULK:     "gpt-4.1-mini",       # Cost-efficient coding, $0.40/$1.60
    Tier.FAST:     "gpt-5-nano",         # Cheapest reasoning, $0.05/$0.40
    Tier.VISION:   "claude-sonnet-4-6",  # Native vision support
}

def _get_model(tier: Tier) -> str:
    """Return model for tier, honouring FORGE_MODEL_<TIER> env override."""
    return os.environ.get(f"FORGE_MODEL_{tier.value.upper()}", _DEFAULT_MODELS[tier])

def get_models() -> dict[Tier, str]:
    """Return every active model (useful for logging/debugging)."""
    return {tier: _get_model(tier) for tier in Tier}

MODELS = get_models()


# ── Max output tokens ─────────────────────────────────────────────────────────
# Raised from legacy 4096/8192.
# Sonnet 4.6 → 64k output; Opus 4.6 → 128k output; GPT-4.1 → 32k output.

_DEFAULT_MAX_TOKENS: dict[Tier, int] = {
    Tier.HEAVY:    64_000,  # Opus 4.6 supports 128k; 64k is generous for any task
    Tier.STANDARD: 32_000,  # Sonnet 4.6 supports 64k; 32k avoids truncation on large JSON
    Tier.DESIGN:   32_000,  # Component specs + design tokens can be large
    Tier.WRITING:  16_000,  # READMEs, pitch decks, demo scripts
    Tier.BULK:     8_000,   # Tests + boilerplate rarely exceed 8k
    Tier.FAST:     4_000,   # Short classification/scoring outputs
    Tier.VISION:   16_000,  # Screenshot audit reports
}

def _get_max_tokens(tier: Tier) -> int:
    """Return max_tokens for tier, honouring FORGE_MAX_TOKENS_<TIER> env override."""
    raw = os.environ.get(f"FORGE_MAX_TOKENS_{tier.value.upper()}")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                f"[forge:llm] Invalid FORGE_MAX_TOKENS_{tier.value.upper()}='{raw}', "
                f"using default {_DEFAULT_MAX_TOKENS[tier]}"
            )
    return _DEFAULT_MAX_TOKENS[tier]

MAX_TOKENS = {tier: _get_max_tokens(tier) for tier in Tier}


# ── Default temperatures ──────────────────────────────────────────────────────

DEFAULT_TEMP: dict[Tier, float] = {
    Tier.HEAVY:    0.1,
    Tier.STANDARD: 0.2,
    Tier.DESIGN:   0.7,   # High creativity for design work
    Tier.WRITING:  0.4,
    Tier.BULK:     0.0,
    Tier.FAST:     0.0,
    Tier.VISION:   0.2,
}


# ── Fallback chain ────────────────────────────────────────────────────────────
# Built dynamically so it works regardless of model overrides.

def _build_fallback() -> dict[str, str]:
    ordered = [Tier.HEAVY, Tier.STANDARD, Tier.WRITING, Tier.BULK, Tier.FAST]
    chain: dict[str, str] = {}
    for i in range(len(ordered) - 1):
        a, b = _get_model(ordered[i]), _get_model(ordered[i + 1])
        if a != b:  # don't add self-loops when tiers share the same model
            chain[a] = b
    # FAST tier (gpt-5-nano) needs an explicit terminal fallback to gpt-4.1-nano
    fast_model = _get_model(Tier.FAST)
    if fast_model not in chain:
        chain[fast_model] = "gpt-4.1-nano"
    # VISION and DESIGN → STANDARD (may already be there if same model)
    vision_m   = _get_model(Tier.VISION)
    design_m   = _get_model(Tier.DESIGN)
    standard_m = _get_model(Tier.STANDARD)
    writing_m  = _get_model(Tier.WRITING)
    bulk_m     = _get_model(Tier.BULK)
    if vision_m != standard_m:
        chain[vision_m] = standard_m
    if design_m != standard_m:
        chain[design_m] = standard_m
    # Explicit terminal for standard → writing when same model
    if standard_m not in chain:
        chain[standard_m] = writing_m if writing_m != standard_m else bulk_m
    # Legacy model names so old forge.secrets files still fall back correctly
    chain.update({
        "claude-opus-4-5":    standard_m,
        "claude-sonnet-4-5":  writing_m,
        "gemini-2.0-flash":   standard_m,
        "gpt-4o":             writing_m,
        "gpt-4o-mini":        fast_model,
        "gpt-4.1-nano":       fast_model,
    })
    # Remove any self-loops that snuck in
    chain = {k: v for k, v in chain.items() if k != v}
    return chain

FALLBACK = _build_fallback()


# ── Task → tier routing ───────────────────────────────────────────────────────

TASK_TIER: dict[str, Tier] = {
    # Intelligence
    "scout-hackathons":         Tier.FAST,
    "score-hackathon":          Tier.FAST,
    "analyze-competitors":      Tier.STANDARD,
    "profile-judges":           Tier.STANDARD,
    "research-sponsor-apis":    Tier.STANDARD,

    # Strategy
    "generate-concepts":        Tier.STANDARD,
    "write-user-stories":       Tier.STANDARD,
    "create-sprint-plan":       Tier.STANDARD,
    "design-api-contract":      Tier.STANDARD,
    "design-db-schema":         Tier.STANDARD,
    "debug-architecture":       Tier.HEAVY,

    # Design — highest impact on hackathon outcome
    "design-system-create":     Tier.DESIGN,
    "generate-color-palette":   Tier.DESIGN,
    "write-component-spec":     Tier.DESIGN,
    "critique-design":          Tier.DESIGN,
    "generate-design-tokens":   Tier.DESIGN,
    "write-ux-copy":            Tier.WRITING,
    "audit-visual-hierarchy":   Tier.VISION,
    "generate-brand-identity":  Tier.DESIGN,

    # Build
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

    # Verify
    "review-code":              Tier.STANDARD,
    "audit-ux-flow":            Tier.DESIGN,
    "check-accessibility":      Tier.STANDARD,
    "run-lighthouse-analysis":  Tier.FAST,
    "security-scan":            Tier.STANDARD,

    # Polish
    "polish-animations":        Tier.STANDARD,
    "rewrite-ux-copy":          Tier.WRITING,
    "seed-demo-data":           Tier.BULK,
    "generate-logo":            Tier.DESIGN,
    "generate-og-image":        Tier.DESIGN,

    # Submission
    "write-demo-script":        Tier.WRITING,
    "write-readme":             Tier.WRITING,
    "write-pitch-deck":         Tier.WRITING,
    "write-submission-copy":    Tier.WRITING,

    # Browser
    "browser-act":              Tier.FAST,
    "browser-extract":          Tier.FAST,
}


def resolve(task: str) -> tuple[str, Tier]:
    """Return (model_id, tier) for a given task name."""
    tier = TASK_TIER.get(task, Tier.STANDARD)
    return _get_model(tier), tier


# ── Core helpers ──────────────────────────────────────────────────────────────

Message = dict[str, str]
T = TypeVar("T", bound=BaseModel)


async def _compress_messages(messages: list[Message], system_prompt: str | None) -> list[Message]:
    """
    Compress conversation history when context limit is hit.
    Adapted from Claude Code's /compact command pattern.

    Keeps the last 3 messages verbatim; summarises everything older.
    The system_prompt is NOT included in the summary text — the caller
    prepends it separately, so no leak into user-visible history.
    """
    if len(messages) <= 4:
        return messages

    recent = messages[-3:]
    older  = messages[:-3]
    summary_text = "\n".join(
        f"[{m.get('role', 'user').upper()}]: {str(m.get('content', ''))[:300]}"
        for m in older
    )
    summary_msg: Message = {
        "role": "user",
        "content": (
            f"[Context compressed — {len(older)} earlier messages summarised]\n"
            f"Prior conversation summary:\n{summary_text[:1500]}\n\n"
            f"Continuing from the most recent context:"
        ),
    }
    compressed = [summary_msg] + recent
    logger.info(f"[forge:llm] Context compressed: {len(messages)} → {len(compressed)} messages")
    return compressed


async def complete(
    *,
    task: str,
    messages: list[Message],
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_retries: int = 3,
) -> str:
    """
    Core LLM call. Resolves model from task name, respects env/secrets overrides,
    applies context compression on overflow, falls back on rate limits.
    """
    model, tier   = resolve(task)
    temp          = temperature if temperature is not None else DEFAULT_TEMP[tier]
    max_tok       = _get_max_tokens(tier)
    current_model = model

    full_messages: list[Message] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    client = get_client()

    for attempt in range(max_retries):
        try:
            logger.info(
                f"[forge:llm] → {current_model} | task={task} | attempt={attempt+1}/{max_retries} "
                f"| max_tokens={max_tok}"
            )
            import time as _t
            t0 = _t.monotonic()

            # Stream to avoid Cloudflare 504 timeouts on long generations
            chunks: list[str] = []
            chunk_count = 0
            stream = await client.chat.completions.create(
                model=current_model,
                messages=full_messages,  # type: ignore[arg-type]
                max_tokens=max_tok,
                temperature=temp,
                stream=True,
            )

            STREAM_TIMEOUT = 600  # 10 min total ceiling
            STALL_TIMEOUT = 90   # kill if no new chunk for 90s (actually stalled)
            last_chunk_at = _t.monotonic()

            async def _read_stream():
                nonlocal chunk_count, last_chunk_at
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        chunks.append(delta.content)
                        chunk_count += 1
                        last_chunk_at = _t.monotonic()

            stream_was_killed = False

            async def _read_with_stall_detection():
                nonlocal stream_was_killed
                read_task = asyncio.create_task(_read_stream())
                while not read_task.done():
                    await asyncio.sleep(5)
                    if read_task.done():
                        break
                    stall = _t.monotonic() - last_chunk_at
                    total = _t.monotonic() - t0
                    if stall > STALL_TIMEOUT:
                        logger.warning(
                            f"[forge:llm] ⏰ Stream stalled {stall:.0f}s (no new chunks) "
                            f"on {current_model} for task={task}"
                        )
                        stream_was_killed = True
                        read_task.cancel()
                        return
                    if total > STREAM_TIMEOUT:
                        logger.warning(
                            f"[forge:llm] ⏰ Stream hit {STREAM_TIMEOUT}s ceiling "
                            f"on {current_model} for task={task}"
                        )
                        stream_was_killed = True
                        read_task.cancel()
                        return
                await read_task

            try:
                await asyncio.wait_for(_read_with_stall_detection(), timeout=STREAM_TIMEOUT + 30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stream_was_killed = True

            if stream_was_killed and chunks:
                elapsed = _t.monotonic() - t0
                partial = "".join(chunks)
                logger.warning(
                    f"[forge:llm] ⏰ Stream killed after {elapsed:.0f}s on {current_model} "
                    f"for task={task} | {chunk_count} chunks, {len(partial)} chars received"
                )
                if len(partial) > 200:
                    logger.info(f"[forge:llm] Using partial response ({len(partial)} chars)")
                    return partial
                raise asyncio.TimeoutError()

            result = "".join(chunks)
            elapsed = _t.monotonic() - t0
            logger.info(
                f"[forge:llm] ✓ {current_model} | task={task} | {elapsed:.1f}s "
                f"| {chunk_count} chunks | {len(result)} chars"
            )

            if not result.strip():
                fb = FALLBACK.get(current_model)
                if fb:
                    logger.warning(
                        f"[forge:llm] Empty response from {current_model} for task={task} "
                        f"→ retrying with {fb} (attempt {attempt+1})"
                    )
                    current_model = fb
                    await asyncio.sleep(1)
                    continue
                logger.warning(
                    f"[forge:llm] Empty response from {current_model} for task={task} "
                    f"→ retrying same model (attempt {attempt+1})"
                )
                await asyncio.sleep(2 ** attempt)
                continue

            return result

        except APIStatusError as e:
            # Context length exceeded — compress and retry once
            if e.status_code == 400 and "context" in str(e).lower():
                logger.warning(
                    f"[forge:llm] Context length exceeded for task={task} "
                    f"model={current_model} — compressing"
                )
                compressed = await _compress_messages(messages, system_prompt)
                if len(compressed) < len(messages):
                    messages = compressed
                    full_messages = []
                    if system_prompt:
                        full_messages.append({"role": "system", "content": system_prompt})
                    full_messages.extend(messages)
                    continue
                raise  # already at minimum

            # Rate limit or server error — fall back to cheaper model
            if e.status_code in (429, 500, 502, 503, 504):
                fb = FALLBACK.get(current_model)
                if fb:
                    logger.warning(
                        f"[forge:llm] {e.status_code} on {current_model} → fallback to {fb}"
                    )
                    current_model = fb
                    await asyncio.sleep(2 ** attempt)
                    continue
            raise

        except asyncio.TimeoutError:
            logger.warning(
                f"[forge:llm] ⏰ Stream timed out on {current_model} for task={task} "
                f"(attempt {attempt+1}/{max_retries}) — retrying with fallback"
            )
            fb = FALLBACK.get(current_model)
            if fb:
                current_model = fb
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            raise

        except Exception as e:
            logger.warning(
                f"[forge:llm] {type(e).__name__} on {current_model} for task={task}: {e} "
                f"(attempt {attempt+1}/{max_retries})"
            )
            if attempt < max_retries - 1:
                fb = FALLBACK.get(current_model)
                if fb:
                    current_model = fb
                await asyncio.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError(f"[forge:llm] exhausted {max_retries} retries for task={task}")


async def complete_json(
    *,
    task: str,
    messages: list[Message],
    response_model: Type[T],
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_json_retries: int = 3,
) -> T:
    """Call complete() and parse the response as a Pydantic model. Retries on parse failure."""
    schema = json.dumps(response_model.model_json_schema(), indent=2)
    sys = (system_prompt or "") + f"\n\nRespond ONLY with valid JSON matching:\n{schema}"
    logger.info(
        f"[forge:llm] complete_json(task={task}, model={response_model.__name__}, "
        f"max_retries={max_json_retries})"
    )

    last_error: Exception | None = None
    for attempt in range(max_json_retries):
        logger.info(f"[forge:llm] complete_json attempt {attempt+1}/{max_json_retries} for task={task}")
        raw = await complete(task=task, messages=messages, system_prompt=sys, temperature=temperature)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        # Strip leading non-JSON garbage (some models emit prose before JSON)
        if cleaned and not cleaned.startswith(("{", "[")):
            brace = cleaned.find("{")
            bracket = cleaned.find("[")
            start = min(p for p in (brace, bracket) if p >= 0) if max(brace, bracket) >= 0 else -1
            if start > 0:
                cleaned = cleaned[start:]
        try:
            return response_model.model_validate(json.loads(cleaned))
        except (json.JSONDecodeError, Exception) as e:
            last_error = e
            logger.warning(
                f"[forge:llm] JSON parse failed for task={task} (attempt {attempt+1}/{max_json_retries}): "
                f"{type(e).__name__}: {e}\n"
                f"  Response preview: {cleaned[:200]!r}"
            )
            if attempt < max_json_retries - 1:
                await asyncio.sleep(1)

    raise last_error or RuntimeError(f"[forge:llm] JSON parse failed after {max_json_retries} retries")


async def embed(text: str) -> list[float]:
    """Generate a text embedding via ElectronHub (text-embedding-3-small)."""
    resp = await get_client().embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


async def complete_batch(
    tasks: list[dict[str, Any]],
    concurrency: int = 5,
) -> list[str]:
    """Run multiple complete() calls in parallel with a concurrency cap."""
    sem = asyncio.Semaphore(concurrency)
    async def _run(item: dict[str, Any]) -> str:
        async with sem:
            return await complete(**item)
    return list(await asyncio.gather(*[_run(t) for t in tasks]))
