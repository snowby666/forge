# -*- coding: utf-8 -*-
"""
ElectronHub API client — single source of truth for all LLM calls.
Base URL: https://api.electronhub.ai/v1 (OpenAI-compatible)

NEVER instantiate AsyncOpenAI directly in agent code.
ALWAYS import complete(), complete_json(), or embed() from here.

Model overrides — set any of these in .env:
  FORGE_MODEL_HEAVY    default: claude-opus-4-6
  FORGE_MODEL_STANDARD default: claude-sonnet-4-6
  FORGE_MODEL_DESIGN   default: claude-sonnet-4-6
  FORGE_MODEL_WRITING  default: gpt-4.1
  FORGE_MODEL_BULK     default: gpt-4.1-mini
  FORGE_MODEL_FAST     default: gpt-5-nano
  FORGE_MODEL_VISION   default: claude-sonnet-4-6  (vision-capable)

Max token overrides per tier:
  FORGE_MAX_TOKENS_HEAVY    default: 96000
  FORGE_MAX_TOKENS_STANDARD default: 64000
  FORGE_MAX_TOKENS_DESIGN   default: 64000
  FORGE_MAX_TOKENS_WRITING  default: 32000
  FORGE_MAX_TOKENS_BULK     default: 16000
  FORGE_MAX_TOKENS_FAST     default: 8000
  FORGE_MAX_TOKENS_VISION   default: 32000

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
import contextvars
import json
import logging
import os
import re
import time as _t
from enum import Enum
from typing import Any, Type, TypeVar

from openai import AsyncOpenAI, APIStatusError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_last_usage: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "last_llm_usage", default={},
)

# Context vars for automatic cost tracking per hackathon/agent
_ctx_hackathon_id: contextvars.ContextVar[str] = contextvars.ContextVar("hackathon_id", default="")
_ctx_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar("agent_id", default="")

def set_llm_context(hackathon_id: str, agent_id: str) -> None:
    """Set the current hackathon/agent context for automatic cost tracking."""
    _ctx_hackathon_id.set(hackathon_id)
    _ctx_agent_id.set(agent_id)

def get_last_usage() -> dict[str, Any]:
    """Return usage data from the most recent complete() call (task-local).
    Keys: model, prompt_tokens, completion_tokens, elapsed_s."""
    return dict(_last_usage.get({}))


# ── Singleton client ──────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        key = os.environ.get("ELECTRONHUB_API_KEY")
        if not key:
            raise RuntimeError(
                "ELECTRONHUB_API_KEY not set. "
                "Add it to .env: ELECTRONHUB_API_KEY=your_key"
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

_DEFAULT_MAX_TOKENS: dict[Tier, int | None] = {
    Tier.HEAVY:    None,    # Opus 4.6 — let the API use the model's full output limit
    Tier.STANDARD: None,    # Sonnet 4.6 — no artificial cap
    Tier.DESIGN:   None,    # Component specs can be 100k+ chars, never truncate
    Tier.WRITING:  32_000,  # READMEs, pitch decks, demo scripts
    Tier.BULK:     16_000,  # Tests + boilerplate
    Tier.FAST:     8_000,   # Classification/scoring outputs
    Tier.VISION:   32_000,  # Screenshot audit reports
}

def _get_max_tokens(tier: Tier) -> int | None:
    """Return max_tokens for tier, honouring FORGE_MAX_TOKENS_<TIER> env override.

    Returns None for tiers where we don't want to cap output — the API will use
    the model's native maximum, and our stream timeouts act as the safety net.
    """
    raw = os.environ.get(f"FORGE_MAX_TOKENS_{tier.value.upper()}")
    if raw:
        try:
            val = int(raw)
            return val if val > 0 else None
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
    # Legacy model names so old .env files still fall back correctly
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
                f"| max_tokens={max_tok or 'unlimited'}"
            )
            t0 = _t.monotonic()

            # Stream to avoid Cloudflare 504 timeouts on long generations
            chunks: list[str] = []
            chunk_count = 0
            usage_data: dict[str, int] = {}
            create_kwargs: dict[str, Any] = dict(
                model=current_model,
                messages=full_messages,  # type: ignore[arg-type]
                temperature=temp,
                stream=True,
                stream_options={"include_usage": True},
            )
            if max_tok is not None:
                create_kwargs["max_tokens"] = max_tok
            stream = await client.chat.completions.create(**create_kwargs)

            STREAM_TIMEOUT = 600  # 10 min total ceiling
            STALL_TIMEOUT = 120  # kill only if no new chunk for 2 full minutes

            last_chunk_at = _t.monotonic()

            async def _read_stream():
                nonlocal chunk_count, last_chunk_at, usage_data
                async for chunk in stream:
                    if chunk.usage:
                        usage_data = {
                            "prompt_tokens": chunk.usage.prompt_tokens or 0,
                            "completion_tokens": chunk.usage.completion_tokens or 0,
                            "total_tokens": chunk.usage.total_tokens or 0,
                        }
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        chunks.append(delta.content)
                        chunk_count += 1
                        last_chunk_at = _t.monotonic()

            read_task = asyncio.create_task(_read_stream())
            try:
                while not read_task.done():
                    await asyncio.sleep(5)
                    if read_task.done():
                        break
                    stall = _t.monotonic() - last_chunk_at
                    total = _t.monotonic() - t0
                    if stall > STALL_TIMEOUT:
                        logger.warning(
                            f"[forge:llm] ⏰ Stream stalled {stall:.0f}s (no chunks) "
                            f"on {current_model} for task={task} | "
                            f"{chunk_count} chunks so far"
                        )
                        read_task.cancel()
                        break
                    if total > STREAM_TIMEOUT:
                        logger.warning(
                            f"[forge:llm] ⏰ Stream hit {STREAM_TIMEOUT}s ceiling "
                            f"on {current_model} for task={task}"
                        )
                        read_task.cancel()
                        break
            except Exception:
                read_task.cancel()

            try:
                await read_task
            except (asyncio.CancelledError, Exception):
                pass

            result = "".join(chunks)
            elapsed = _t.monotonic() - t0
            prompt_tok = usage_data.get("prompt_tokens", 0)
            completion_tok = usage_data.get("completion_tokens", 0)
            logger.info(
                f"[forge:llm] ✓ {current_model} | task={task} | {elapsed:.1f}s "
                f"| {chunk_count} chunks | {len(result)} chars"
                f" | tokens={prompt_tok}+{completion_tok}"
            )
            _last_usage.set({
                "model": current_model,
                "prompt_tokens": prompt_tok,
                "completion_tokens": completion_tok,
                "elapsed_s": round(elapsed, 2),
            })

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

            # Auto-track cost if context is set
            hid = _ctx_hackathon_id.get("")
            aid = _ctx_agent_id.get("")
            if prompt_tok or completion_tok:
                if hid and aid:
                    try:
                        from config.forge_tools import track_agent_cost
                        from config.redis_client import get_redis
                        r = get_redis()
                        try:
                            await track_agent_cost(r, hid, aid, current_model, prompt_tok, completion_tok)
                        finally:
                            await r.aclose()
                    except Exception:
                        pass

            # Emit trace span for this LLM call
            try:
                from config.forge_trace import emit_span
                await emit_span(
                    hackathon_id=hid,
                    agent_id=aid,
                    op="llm",
                    name=f"complete:{task}",
                    elapsed_s=elapsed,
                    span_input={
                        "model": current_model,
                        "task": task,
                        "tier": tier.name if tier else "unknown",
                        "messages_count": len(full_messages),
                        "max_tokens": max_tok,
                        "attempt": attempt + 1,
                    },
                    span_output={
                        "prompt_tokens": prompt_tok,
                        "completion_tokens": completion_tok,
                        "chars": len(result),
                        "chunks": chunk_count,
                    },
                )
            except Exception:
                pass

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


def _repair_truncated_json(s: str) -> str:
    """Best-effort repair of truncated JSON by closing open strings/brackets."""
    in_string = False
    escaped = False
    stack: list[str] = []
    for ch in s:
        if escaped:
            escaped = False
            continue
        if ch == '\\' and in_string:
            escaped = True
            continue
        if ch == '"' and not escaped:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append('}' if ch == '{' else ']')
        elif ch in ('}', ']') and stack:
            stack.pop()

    repaired = s
    if in_string:
        repaired += '"'
    while stack:
        repaired += stack.pop()
    return repaired


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
    _json_t0 = _t.monotonic()
    for attempt in range(max_json_retries):
        logger.info(f"[forge:llm] complete_json attempt {attempt+1}/{max_json_retries} for task={task}")
        raw = await complete(task=task, messages=messages, system_prompt=sys, temperature=temperature)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if cleaned and not cleaned.startswith(("{", "[")):
            brace = cleaned.find("{")
            bracket = cleaned.find("[")
            start = min(p for p in (brace, bracket) if p >= 0) if max(brace, bracket) >= 0 else -1
            if start > 0:
                cleaned = cleaned[start:]
        # Strip NUL and other non-printable control chars (keep \t \n \r)
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
        try:
            # strict=False allows literal control characters (\n, \t) inside
            # JSON string values — LLMs frequently emit these unescaped.
            parsed = response_model.model_validate(json.loads(cleaned, strict=False))
            # Trace the successful complete_json
            try:
                from config.forge_trace import emit_span
                await emit_span(
                    hackathon_id=_ctx_hackathon_id.get(""),
                    agent_id=_ctx_agent_id.get(""),
                    op="llm",
                    name=f"complete_json:{task}",
                    elapsed_s=_t.monotonic() - _json_t0,
                    span_input={"model_name": response_model.__name__, "attempts": attempt + 1},
                    span_output={"parsed": True, "response_chars": len(cleaned)},
                )
            except Exception:
                pass
            return parsed
        except json.JSONDecodeError as e:
            # Attempt repair on truncated output (stream stall / max_tokens)
            if "Unterminated" in str(e) or "Expecting" in str(e) or "end of" in str(e).lower():
                try:
                    repaired = _repair_truncated_json(cleaned)
                    logger.info(f"[forge:llm] Attempting JSON repair for task={task} (+{len(repaired)-len(cleaned)} chars)")
                    parsed = response_model.model_validate(json.loads(repaired, strict=False))
                    try:
                        from config.forge_trace import emit_span
                        await emit_span(
                            hackathon_id=_ctx_hackathon_id.get(""),
                            agent_id=_ctx_agent_id.get(""),
                            op="llm",
                            name=f"complete_json:{task}",
                            elapsed_s=_t.monotonic() - _json_t0,
                            span_input={"model_name": response_model.__name__, "attempts": attempt + 1},
                            span_output={"parsed": True, "repaired": True, "response_chars": len(repaired)},
                        )
                    except Exception:
                        pass
                    return parsed
                except Exception:
                    pass
            last_error = e
            logger.warning(
                f"[forge:llm] JSON parse failed for task={task} (attempt {attempt+1}/{max_json_retries}): "
                f"{type(e).__name__}: {e}\n"
                f"  Response preview: {cleaned[:200]!r}"
            )
            if attempt < max_json_retries - 1:
                await asyncio.sleep(1)
        except Exception as e:
            last_error = e
            logger.warning(
                f"[forge:llm] JSON validation failed for task={task} (attempt {attempt+1}/{max_json_retries}): "
                f"{type(e).__name__}: {e}\n"
                f"  Response preview: {cleaned[:200]!r}"
            )
            if attempt < max_json_retries - 1:
                await asyncio.sleep(1)

    # Trace the failure
    try:
        from config.forge_trace import emit_span
        await emit_span(
            hackathon_id=_ctx_hackathon_id.get(""),
            agent_id=_ctx_agent_id.get(""),
            op="llm",
            name=f"complete_json:{task}",
            status="error",
            elapsed_s=_t.monotonic() - _json_t0,
            span_input={"model_name": response_model.__name__, "attempts": max_json_retries},
            error=str(last_error)[:500] if last_error else "unknown",
        )
    except Exception:
        pass
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
