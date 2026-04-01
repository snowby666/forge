# -*- coding: utf-8 -*-
"""
Monitor Agent + Calendar Agent — Layer 7: Infrastructure
Monitor: tracks cost, latency, errors, circuit breakers, Discord alerts.
Calendar: schedules human checkpoint events directly via Google Calendar API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

    def is_circuit_open(self, agent_id: str, threshold: int = 3, encoding="utf-8") -> bool:
        return self.consecutive_failures.get(agent_id, 0) >= threshold


_metrics = AgentMetrics()


async def send_discord_alert(message: str) -> None:
    """Send an alert to the Forge Discord channel via webhook."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        logger.warning(f"[forge:monitor] DISCORD_WEBHOOK_URL not set — alert: {message}")
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                webhook,
                json={"content": message},
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        logger.error(f"[forge:monitor] Discord alert failed: {e}")


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
                if _metrics.is_circuit_open(agent_id, encoding="utf-8"):
                    await send_discord_alert(
                        f":warning: **Circuit breaker open** for `{agent_id}` on hackathon `{hackathon_id}`\n"
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
                        await send_discord_alert(
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

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE CALENDAR — direct API integration (no n8n needed)
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_PATH = Path(os.path.dirname(__file__)).parent.parent.parent / "forge-google-token.json"


def _get_google_creds():
    """Load or refresh Google OAuth2 credentials."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        logger.warning("[forge:calendar] google-auth not installed — run: pip install google-auth google-auth-oauthlib google-api-python-client")
        return None

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning("[forge:calendar] GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set — skipping calendar")
        return None

    creds = None
    if _TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH))
        except Exception:
            pass

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json())
        except Exception as e:
            logger.warning(f"[forge:calendar] Token refresh failed: {e}")
            creds = None

    if not creds or not creds.valid:
        logger.warning(
            "[forge:calendar] No valid token. Run 'forge calendar-auth' to authorize."
        )
        return None

    return creds


async def _create_calendar_event(service, event_body: dict) -> str | None:
    """Create a single Google Calendar event (runs in executor to avoid blocking)."""
    import functools
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            functools.partial(
                service.events().insert,
                calendarId="primary",
                body=event_body,
            ),
        )
        created = await loop.run_in_executor(None, result.execute)
        return created.get("htmlLink", "")
    except Exception as e:
        logger.error(f"[forge:calendar] Failed to create event: {e}")
        return None


async def schedule_hackathon_events(
    hackathon_id: str,
    hackathon_name: str,
    deadline_iso: str,
    preview_url: str = "",
) -> list[dict]:
    """Schedule all human checkpoint events directly via Google Calendar API."""
    try:
        deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
    except Exception:
        deadline = datetime.now(timezone.utc) + timedelta(days=7)

    now = datetime.now(timezone.utc)
    approve_base = os.environ.get("N8N_BASE_URL", "http://localhost:5678")

    events = [
        {
            "title": f"[Forge] {hackathon_name} — Concept pick",
            "start": now,
            "duration_minutes": 15,
            "description": (
                f"3 project concepts ready for review. Agent is waiting.\n\n"
                f"Approve at: {approve_base}/webhook/{hackathon_id}/concept_approval\n\n"
                f"The agent has analyzed:\n"
                f"- Past winners and failure patterns\n"
                f"- Judge panel backgrounds and preferences\n"
                f"- Top sponsor API opportunities\n\n"
                f"Pick one concept and the build starts immediately."
            ),
        },
        {
            "title": f"[Forge] {hackathon_name} — Design review",
            "start": now + timedelta(hours=4),
            "duration_minutes": 10,
            "description": (
                f"UI/UX designs ready. Frontend build is BLOCKED until you approve.\n\n"
                f"Approve at: {approve_base}/webhook/{hackathon_id}/design_approval"
            ),
        },
        {
            "title": f"[Forge] {hackathon_name} — Quality review",
            "start": deadline - timedelta(hours=6),
            "duration_minutes": 20,
            "description": (
                f"App built and quality-checked. Review live preview before polish.\n\n"
                f"Preview: {preview_url or 'URL pending'}\n"
                f"Approve at: {approve_base}/webhook/{hackathon_id}/quality_review"
            ),
        },
        {
            "title": f"[Forge] {hackathon_name} — SUBMIT APPROVAL",
            "start": deadline - timedelta(hours=1, minutes=30),
            "duration_minutes": 10,
            "description": (
                f"All submission materials ready. FINAL review before submitting.\n\n"
                f"Approve at: {approve_base}/webhook/{hackathon_id}/submission_approval\n\n"
                f"Deadline: {deadline.strftime('%B %d at %I:%M %p UTC')}"
            ),
        },
        {
            "title": f"[Forge] {hackathon_name} — DEMO DAY",
            "start": deadline,
            "duration_minutes": 5,
            "description": (
                f"Submitted! Live URL: {preview_url or 'check Devpost'}\n"
                f"Talking points: /tmp/hackathon-{hackathon_id}/demo-script.txt"
            ),
        },
    ]

    creds = _get_google_creds()
    if not creds:
        logger.info(f"[forge:calendar] Scheduled {len(events)} events (local only — no Google token)")
        return events

    try:
        from googleapiclient.discovery import build as build_service
        service = build_service("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"[forge:calendar] Could not build Calendar service: {e}")
        return events

    created_count = 0
    for ev in events:
        start_dt = ev["start"]
        end_dt = start_dt + timedelta(minutes=ev["duration_minutes"])
        body = {
            "summary": ev["title"],
            "description": ev["description"],
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            "reminders": {"useDefault": False, "overrides": [
                {"method": "popup", "minutes": 10},
            ]},
        }
        link = await _create_calendar_event(service, body)
        if link:
            created_count += 1
            logger.info(f"[forge:calendar] Created: {ev['title']}")

    logger.info(f"[forge:calendar] Scheduled {created_count}/{len(events)} events for {hackathon_name}")
    return events


def run_calendar_auth() -> None:
    """One-time OAuth flow — run 'forge calendar-auth' to authorize."""
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
    except ImportError:
        print("Missing dependency. Run:\n  pip install google-auth google-auth-oauthlib google-api-python-client")
        return

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret or "your_" in client_id:
        print("\n  ┌─────────────────────────────────────────────────────────┐")
        print("  │  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set        │")
        print("  │                                                         │")
        print("  │  Create credentials (takes 2 minutes):                  │")
        print("  │  1. Go to console.cloud.google.com/apis/credentials     │")
        print("  │  2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'    │")
        print("  │  3. Application type: 'Desktop app', name: 'Forge'      │")
        print("  │  4. Copy the Client ID and Client Secret                │")
        print("  │  5. Also enable 'Google Calendar API' under APIs        │")
        print("  │  6. Add them to ~/forge/.env:                           │")
        print("  │     GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com   │")
        print("  │     GOOGLE_CLIENT_SECRET=GOCSPX-xxxxx                   │")
        print("  └─────────────────────────────────────────────────────────┘")
        return

    SCOPES = "https://www.googleapis.com/auth/calendar.events"
    REDIRECT_URI = "http://localhost"

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print(f"\n  1. Open this URL in ANY browser:\n")
    print(f"     {auth_url}\n")
    print(f"  2. Sign in and click 'Allow'")
    print(f"  3. You'll be redirected to a page that WON'T LOAD (that's normal)")
    print(f"  4. Copy the FULL URL from your browser's address bar")
    print(f"     (it looks like: http://localhost/?code=4/0Axx...&scope=...)\n")

    redirect_url = input("  Paste the full redirect URL here: ").strip()
    if not redirect_url:
        print("  No URL entered. Aborting.")
        return

    # Extract code from redirect URL
    import urllib.parse
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]

    if not code:
        if redirect_url.startswith("4/") or len(redirect_url) > 20 and "." not in redirect_url[:10]:
            code = redirect_url
        else:
            print("  Could not find authorization code in that URL. Try again.")
            return

    # Exchange code for tokens
    try:
        import urllib.request
        data = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read().decode())
    except Exception as e:
        print(f"\n  Token exchange failed: {e}")
        return

    if "error" in tokens:
        print(f"\n  Google error: {tokens['error']} — {tokens.get('error_description', '')}")
        return

    token_data = {
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": [SCOPES],
    }
    _TOKEN_PATH.write_text(json.dumps(token_data, indent=2))
    print(f"\n  Token saved to {_TOKEN_PATH}")
    print("  Google Calendar connected! Test with: forge calendar-test")


async def calendar_test() -> bool:
    """Create a test event to verify Google Calendar works."""
    creds = _get_google_creds()
    if not creds:
        return False

    try:
        from googleapiclient.discovery import build as build_service
        service = build_service("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"[forge:calendar] Service build failed: {e}")
        return False

    now = datetime.now(timezone.utc)
    body = {
        "summary": "[Forge] Calendar Test — delete me",
        "description": "This is a test event from Forge. You can safely delete it.",
        "start": {"dateTime": (now + timedelta(minutes=5)).isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + timedelta(minutes=15)).isoformat(), "timeZone": "UTC"},
    }
    link = await _create_calendar_event(service, body)
    if link:
        print(f"  Test event created: {link}")
        return True
    return False


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
