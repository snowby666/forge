"""
forge_trace — Structured span/event tracing for Forge agents.

Every meaningful operation (LLM call, MCP, HTTP, file I/O, Redis write,
subprocess) is captured as a "span" and stored in Redis for the dashboard.

Usage in agent code:

    from config.forge_trace import trace_op, register_artifact, set_trace_context

    set_trace_context(hackathon_id, agent_id)

    async with trace_op("mcp", "stitch:generate_screens") as span:
        span.input = {"project_id": pid, "screen_count": 3}
        result = await call_stitch(...)
        span.output = {"image_urls": result.urls}

    await register_artifact(hackathon_id, "ui_ux_designer",
        "DESIGN.md", "markdown", "Full design specification (42 KB)")
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("forge.trace")

# Re-use electronhub's context vars when available; provide fallback
_ctx_hackathon_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_hackathon_id", default=""
)
_ctx_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_agent_id", default=""
)

EVENT_LIST_CAP = 5000
EVENT_TTL = 604800  # 7 days
EVENT_KEY_PREFIX = "events"  # unified key: events:{hackathon_id}
# Legacy key kept as alias for backward compat during migration
SPAN_LIST_CAP = EVENT_LIST_CAP
SPAN_TTL = EVENT_TTL


def set_trace_context(hackathon_id: str, agent_id: str) -> None:
    """Set the hackathon/agent context for automatic span tagging."""
    _ctx_hackathon_id.set(hackathon_id)
    _ctx_agent_id.set(agent_id)


def set_agent_context(hackathon_id: str, agent_id: str) -> None:
    """Unified context setter — sets BOTH trace and LLM context vars in one call."""
    _ctx_hackathon_id.set(hackathon_id)
    _ctx_agent_id.set(agent_id)
    try:
        from config.electronhub import set_llm_context
        set_llm_context(hackathon_id, agent_id)
    except Exception:
        pass


def _get_ctx_hackathon() -> str:
    """Read hackathon ID from trace context, falling back to electronhub's."""
    val = _ctx_hackathon_id.get("")
    if val:
        return val
    try:
        from config.electronhub import _ctx_hackathon_id as eh_hid
        return eh_hid.get("")
    except Exception:
        return ""


def _get_ctx_agent() -> str:
    """Read agent ID from trace context, falling back to electronhub's."""
    val = _ctx_agent_id.get("")
    if val:
        return val
    try:
        from config.electronhub import _ctx_agent_id as eh_aid
        return eh_aid.get("")
    except Exception:
        return ""


class SpanBuilder:
    """Mutable object yielded by trace_op for the caller to populate."""

    __slots__ = ("input", "output", "error", "tags")

    def __init__(self) -> None:
        self.input: dict[str, Any] = {}
        self.output: dict[str, Any] = {}
        self.error: str | None = None
        self.tags: dict[str, Any] = {}


async def _push_event(hackathon_id: str, event: dict) -> None:
    """Append a JSON event to the unified events list in Redis."""
    if not hackathon_id:
        return
    try:
        from config.redis_client import get_redis
        r = get_redis()
        try:
            key = f"{EVENT_KEY_PREFIX}:{hackathon_id}"
            await r.rpush(key, json.dumps(event, default=str))
            await r.ltrim(key, -EVENT_LIST_CAP, -1)
            await r.expire(key, EVENT_TTL)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.debug("Failed to push event %s: %s", event.get("name", "?"), exc)


async def emit_span(
    hackathon_id: str,
    agent_id: str,
    op: str,
    name: str,
    status: str = "ok",
    started_at: str | None = None,
    finished_at: str | None = None,
    elapsed_s: float | None = None,
    span_input: dict[str, Any] | None = None,
    span_output: dict[str, Any] | None = None,
    error: str | None = None,
    tags: dict[str, Any] | None = None,
) -> None:
    """Persist a trace span to the unified events list in Redis."""
    if not hackathon_id:
        return
    span: dict[str, Any] = {
        "kind": "span",
        "id": uuid.uuid4().hex[:12],
        "hackathon_id": hackathon_id,
        "agent_id": agent_id or "unknown",
        "op": op,
        "name": name,
        "status": status,
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "finished_at": finished_at or datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(elapsed_s, 3) if elapsed_s is not None else 0,
    }
    if span_input:
        span["input"] = _safe_truncate(span_input)
    if span_output:
        span["output"] = _safe_truncate(span_output)
    if error:
        span["error"] = str(error)[:2000]
    if tags:
        span["tags"] = tags
    await _push_event(hackathon_id, span)


async def emit_log(
    hackathon_id: str,
    agent_id: str,
    level: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Emit a log-style trace span.  Logs are just spans with op='log'."""
    hid = hackathon_id or _get_ctx_hackathon()
    aid = agent_id or _get_ctx_agent()
    now = datetime.now(timezone.utc).isoformat()
    await emit_span(
        hackathon_id=hid,
        agent_id=aid,
        op="log",
        name=message[:200],
        status="error" if level in ("error", "critical") else "ok",
        started_at=now,
        finished_at=now,
        elapsed_s=0,
        span_output=data,
        tags={"level": level},
    )


def _safe_truncate(d: dict[str, Any], max_str_len: int = 500) -> dict[str, Any]:
    """Truncate long string values in a dict to keep spans compact."""
    out = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > max_str_len:
            out[k] = v[:max_str_len] + f"... ({len(v)} chars)"
        elif isinstance(v, list) and len(v) > 20:
            out[k] = v[:20]
            out[f"_{k}_total"] = len(v)
        elif isinstance(v, dict) and len(str(v)) > max_str_len:
            out[k] = f"<dict with {len(v)} keys>"
        else:
            out[k] = v
    return out


@asynccontextmanager
async def trace_op(
    op: str,
    name: str,
    hackathon_id: str | None = None,
    agent_id: str | None = None,
    **extra_tags: Any,
):
    """Async context manager that auto-records a span.

    Usage:
        async with trace_op("mcp", "stitch:generate") as span:
            span.input = {"screens": 3}
            result = await do_work()
            span.output = {"urls": result}
    """
    hid = hackathon_id or _get_ctx_hackathon()
    aid = agent_id or _get_ctx_agent()
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    builder = SpanBuilder()
    if extra_tags:
        builder.tags = dict(extra_tags)

    status = "ok"
    try:
        yield builder
    except Exception as exc:
        status = "error"
        if not builder.error:
            builder.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        elapsed = time.monotonic() - t0
        finished = datetime.now(timezone.utc).isoformat()
        try:
            await emit_span(
                hackathon_id=hid,
                agent_id=aid,
                op=op,
                name=name,
                status=status,
                started_at=started,
                finished_at=finished,
                elapsed_s=elapsed,
                span_input=builder.input or None,
                span_output=builder.output or None,
                error=builder.error,
                tags=builder.tags or None,
            )
        except Exception:
            pass


async def register_artifact(
    hackathon_id: str,
    agent_id: str,
    name: str,
    artifact_type: str,
    summary: str,
    meta: dict[str, Any] | None = None,
) -> None:
    """Register a named artifact in the artifact registry (Redis hash)."""
    if not hackathon_id:
        return
    entry = {
        "name": name,
        "type": artifact_type,
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary[:1000],
    }
    if meta:
        entry["meta"] = meta

    try:
        from config.redis_client import get_redis
        r = get_redis()
        try:
            key = f"artifacts:{hackathon_id}"
            await r.hset(key, name, json.dumps(entry, default=str))
            await r.expire(key, SPAN_TTL)
        finally:
            await r.aclose()
    except Exception as exc:
        logger.debug("Failed to register artifact %s: %s", name, exc)

    # Also emit as an artifact span
    await emit_span(
        hackathon_id=hackathon_id,
        agent_id=agent_id,
        op="artifact",
        name=f"artifact:{name}",
        span_output={"type": artifact_type, "summary": summary[:200]},
    )
