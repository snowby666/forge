"""
Monitor Agent + Calendar Agent — Layer 7: Infrastructure
Monitor: tracks cost, latency, errors, circuit breakers, Slack alerts.
Calendar: schedules human checkpoint events via Google Calendar MCP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import aiohttp
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MONITOR AGENT
# ─────────────────────────────────────────────────────────────────────────────

class AgentMetrics:
    def __init__(self) -> None:
        self.latencies: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, int] = defaultdict(int)
        self.costs_usd: dict[str, float] = defaultdict(float)
        self.consecutive_failures: dict[str, int] = defaultdict(int)

    def record_latency(self, agent_id: str, latency_ms: float) -> None:
        self.latencies[agent_id].append(latency_ms)
        if len(self.latencies[agent_id]) > 100:
            self.latencies[agent_id] = self.latencies[agent_id][-100:]

    def record_error(self, agent_id: str) -> None:
        self.errors[agent_id] += 1
        self.consecutive_failures[agent_id] += 1

    def record_success(self, agent_id: str) -> None:
        self.consecutive_failures[agent_id] = 0

    def p95_latency(self, agent_id: str) -> float:
        lats = sorted(self.latencies.get(agent_id, [0]))
        idx = int(len(lats) * 0.95)
        return lats[min(idx, len(lats) - 1)]

    def is_circuit_open(self, agent_id: str, threshold: int = 3) -> bool:
        return self.consecutive_failures.get(agent_id, 0) >= threshold


_metrics = AgentMetrics()


async def send_slack_alert(message: str, channel: str | None = None) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        logger.warning(f"[forge:monitor] SLACK_WEBHOOK_URL not set — alert: {message}")
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                webhook,
                json={
                    "text": message,
                    "channel": channel or os.environ.get("SLACK_CHANNEL", "#hackathon-agent"),
                },
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        logger.error(f"[forge:monitor] Slack alert failed: {e}")


async def check_agent_health(hackathon_id: str, redis: Redis) -> dict:
    """Check all active agent task statuses for a hackathon."""
    from config.agents_config import ALL_AGENTS

    health = {}
    for agent_id in ALL_AGENTS:
        raw = await redis.get(f"task:{hackathon_id}:{agent_id}")
        if raw:
            task = json.loads(raw)
            health[agent_id] = task.get("status", "unknown")
            if task.get("status") == "failed":
                _metrics.record_error(agent_id)
                if _metrics.is_circuit_open(agent_id):
                    await send_slack_alert(
                        f"⚠️ *Circuit breaker open* for `{agent_id}` on hackathon `{hackathon_id}`\n"
                        f"Failed {_metrics.consecutive_failures[agent_id]} times in a row.\n"
                        f"Commander should simplify task scope or skip this agent."
                    )
    return health


async def run_monitor_worker() -> None:
    """Continuously monitor all active hackathons."""
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("monitor:record_metric")

    logger.info("[forge:monitor] Monitor worker running")

    async def periodic_check():
        from config.forge_tools import check_due_cron_triggers, get_run_cost_summary
        while True:
            # 1. Check agent health for all active hackathons
            keys = await redis.keys("hackathon:*:brief")
            for key in keys:
                hackathon_id = key.split(":")[1]
                health = await check_agent_health(hackathon_id, redis)
                failed = [a for a, s in health.items() if s == "failed"]
                if failed:
                    logger.warning(f"[forge:monitor] Failed agents for {hackathon_id}: {failed}")

                # 2. Check cost budgets (adapted from Claude Code's cost-tracker.ts)
                try:
                    cost = await get_run_cost_summary(redis, hackathon_id)
                    if cost["total_usd"] > 10.0:
                        await send_slack_alert(
                            f"[forge:monitor] Cost alert for {hackathon_id}: "
                            f"${cost['total_usd']:.2f} total so far\n"
                            f"Top spender: {max(cost['by_agent'].items(), key=lambda x: x[1]['cost_usd'], default=('none', {'cost_usd': 0}))[0]}"
                        )
                except Exception:
                    pass

            # 3. Fire any due cron triggers (adapted from Claude Code's ScheduleCronTool)
            try:
                due = await check_due_cron_triggers(redis)
                for trigger in due:
                    agent_id   = trigger["agent_id"]
                    h_id       = trigger["hackathon_id"]
                    input_data = trigger.get("input_data", {})
                    logger.info(f"[forge:monitor] Firing cron trigger: {trigger['trigger_id']}")
                    await redis.publish("agent:trigger", json.dumps({
                        "hackathon_id": h_id,
                        "agent": agent_id,
                        "input": input_data,
                    }))
            except Exception as e:
                logger.warning(f"[forge:monitor] Cron check failed: {e}")

            await asyncio.sleep(60)  # check every minute

    # Run periodic check in background
    asyncio.create_task(periodic_check())

    # Handle metric recording events
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            payload = json.loads(message["data"])
            agent_id = payload.get("agent_id")
            latency  = payload.get("latency_ms")
            success  = payload.get("success", True)
            if agent_id and latency:
                _metrics.record_latency(agent_id, latency)
            if agent_id and not success:
                _metrics.record_error(agent_id)
            elif agent_id:
                _metrics.record_success(agent_id)
        except Exception:
            pass

    await redis.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR AGENT
# ─────────────────────────────────────────────────────────────────────────────

async def schedule_hackathon_events(
    hackathon_id: str,
    hackathon_name: str,
    deadline_iso: str,
    preview_url: str = "",
) -> list[dict]:
    """
    Schedule all human checkpoint events via n8n → Google Calendar MCP.
    Events are published to Redis and consumed by n8n workflow.
    """
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    try:
        deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
    except Exception:
        deadline = datetime.now(timezone.utc) + timedelta(days=7)

    now = datetime.now(timezone.utc)
    n8n_base = os.environ.get("N8N_BASE_URL", "http://localhost:5678")

    events = [
        {
            "title": f"[Agent] {hackathon_name} — Concept pick (15 min)",
            "start": now.isoformat(),
            "duration_minutes": 15,
            "description": (
                f"3 project concepts ready for review. Agent is waiting.\n\n"
                f"Approve at: {n8n_base}/webhook/{hackathon_id}/concept_approval\n\n"
                f"The agent has analyzed:\n"
                f"• Past winners and failure patterns\n"
                f"• Judge panel backgrounds and preferences\n"
                f"• Top sponsor API opportunities\n\n"
                f"Pick one concept and the build starts immediately."
            ),
        },
        {
            "title": f"[Agent] {hackathon_name} — Design review (10 min)",
            "start": (now + timedelta(hours=4)).isoformat(),
            "duration_minutes": 10,
            "description": (
                f"UI/UX designs ready. Frontend build is BLOCKED until you approve.\n\n"
                f"Approve at: {n8n_base}/webhook/{hackathon_id}/design_approval\n\n"
                f"Review:\n"
                f"• Design personality selection and rationale\n"
                f"• Color system and typography\n"
                f"• All screen mockups from DESIGN.md\n"
                f"• Figma file (if connected)"
            ),
        },
        {
            "title": f"[Agent] {hackathon_name} — Quality review (20 min) ⭐",
            "start": (deadline - timedelta(hours=6)).isoformat(),
            "duration_minutes": 20,
            "description": (
                f"App built and quality-checked. Review live preview before polish.\n\n"
                f"Preview: {preview_url or 'URL pending'}\n"
                f"Approve at: {n8n_base}/webhook/{hackathon_id}/quality_review\n\n"
                f"Check it on mobile too (375px width matters to judges)\n"
                f"UX Auditor score must be ≥ 7.0 — see audit report for details."
            ),
        },
        {
            "title": f"[Agent] {hackathon_name} — SUBMIT APPROVAL ⚠️ (10 min)",
            "start": (deadline - timedelta(hours=1, minutes=30)).isoformat(),
            "duration_minutes": 10,
            "description": (
                f"All submission materials ready. FINAL review before submitting.\n\n"
                f"Approve at: {n8n_base}/webhook/{hackathon_id}/submission_approval\n\n"
                f"Materials ready:\n"
                f"• Live demo: {preview_url or 'URL pending'}\n"
                f"• Demo video (90 seconds, YouTube unlisted)\n"
                f"• README.md\n"
                f"• Pitch deck (Gamma.app)\n"
                f"• Devpost form pre-filled (dry run preview attached)\n\n"
                f"⚠️ Submission deadline: {deadline.strftime('%B %d at %I:%M %p UTC')}"
            ),
        },
        {
            "title": f"[Agent] {hackathon_name} — DEMO DAY 🎯",
            "start": deadline.isoformat(),
            "duration_minutes": 5,
            "description": (
                f"We submitted! Here's everything you need if judges contact you:\n\n"
                f"• Live URL: {preview_url or 'check Devpost'}\n"
                f"• Talking points: /tmp/hackathon-{hackathon_id}/demo-script.txt\n"
                f"• GitHub: check submission page\n\n"
                f"If judges ask technical questions:\n"
                f"• Tech stack: Next.js + FastAPI + PostgreSQL\n"
                f"• AI/ML: via ElectronHub routing to Claude/GPT-4o\n"
                f"• Deployment: Vercel (frontend) + Railway (backend)"
            ),
        },
    ]

    # Publish to Redis for n8n to consume
    await redis.publish("calendar:create_events", json.dumps({
        "hackathon_id": hackathon_id,
        "hackathon_name": hackathon_name,
        "events": events,
    }))

    logger.info(f"[forge:calendar] Scheduled {len(events)} events for {hackathon_name}")
    await redis.aclose()
    return events


async def run_calendar_worker() -> None:
    """Listen for calendar scheduling requests."""
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("commander:new_hackathon")

    logger.info("[forge:calendar] Worker ready")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            payload = json.loads(message["data"])
            hackathon_id = payload["hackathon_id"]
            brief = payload.get("brief", {})
            await schedule_hackathon_events(
                hackathon_id=hackathon_id,
                hackathon_name=brief.get("name", "Hackathon"),
                deadline_iso=brief.get("deadline", ""),
            )
        except Exception as e:
            logger.error(f"[forge:calendar] Failed to schedule events: {e}")

    await redis.aclose()
