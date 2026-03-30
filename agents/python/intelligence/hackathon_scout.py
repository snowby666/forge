"""
Hackathon Scout Agent
=====================
Layer 1 — Intelligence. Runs first, in parallel with other intel agents.

Scrapes Devpost, MLH, Lablab, Devfolio via the TypeScript browser layer.
Scores every opportunity using the rubric. Auto-registers to top candidates.
Publishes HackathonBrief artifacts to the shared message pool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import aiohttp
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from config.electronhub import complete_json
from config.agents_config import ALL_AGENTS

logger = logging.getLogger(__name__)
AGENT = ALL_AGENTS["hackathon_scout"]
BROWSER_URL = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")


# ── Data models ───────────────────────────────────────────────────────────────

class Prize(BaseModel):
    name: str
    amount: float | None = None
    sponsor: str | None = None
    requirements: str | None = None


class SponsorTech(BaseModel):
    sponsor: str
    api_name: str
    docs_url: str | None = None
    prize_amount: float | None = None


class HackathonBrief(BaseModel):
    hackathon_id: str
    name: str
    url: str
    platform: str                   # devpost | mlh | lablab | devfolio
    theme: str
    description: str
    deadline: str                   # ISO datetime
    submission_deadline: str | None = None
    prizes: list[Prize]
    judging_criteria: list[str]
    sponsor_techs: list[SponsorTech]
    registration_open: bool
    team_size_min: int = 1
    team_size_max: int = 5
    total_participants: int | None = None
    # Scoring
    score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    days_until_deadline: int = 0
    recommended: bool = False


class ThemeScore(BaseModel):
    score: int          # 0–20
    reasoning: str


async def score_hackathon(brief: HackathonBrief) -> HackathonBrief:
    """Score a hackathon 0–100 using rule-based scoring + LLM theme analysis."""
    now = datetime.now(timezone.utc)
    try:
        deadline = datetime.fromisoformat(brief.deadline.replace("Z", "+00:00"))
        days_left = max(0, (deadline - now).days)
    except Exception:
        days_left = 7  # default if parse fails

    brief.days_until_deadline = days_left
    total_prize = sum(p.amount or 0 for p in brief.prizes)
    sponsor_prize_count = sum(1 for p in brief.prizes if p.sponsor)

    breakdown: dict[str, int] = {
        "prize_pool": (25 if total_prize >= 10_000 else 15 if total_prize >= 5_000 else 8 if total_prize >= 1_000 else 0),
        "sponsor_prizes": min(sponsor_prize_count * 7, 20),
        "deadline_buffer": (15 if days_left >= 10 else 10 if days_left >= 5 else 5 if days_left >= 3 else 0),
        "theme_match": 0,       # LLM scores this
        "competition_size": 15, # default; updated if participant count known
    }

    if brief.total_participants is not None:
        breakdown["competition_size"] = (
            20 if brief.total_participants < 100 else
            10 if brief.total_participants < 300 else 5
        )

    # LLM theme scoring
    theme_score = await complete_json(
        task="scout-hackathons",
        response_model=ThemeScore,
        messages=[{
            "role": "user",
            "content": (
                f"Score 0–20: How well does this hackathon suit an autonomous AI agent development team?\n"
                f"Theme: {brief.theme}\nDescription: {brief.description[:400]}\n"
                f"Judging: {', '.join(brief.judging_criteria[:4])}\n\n"
                f"20=perfect (AI/ML/automation, agent-building encouraged)\n"
                f"10=good (general tech, AI welcome)\n5=neutral\n0=bad fit"
            ),
        }],
    )
    breakdown["theme_match"] = min(theme_score.score, 20)

    brief.score = sum(breakdown.values())
    brief.score_breakdown = breakdown
    brief.recommended = brief.score >= 65
    return brief


async def call_browser_scrape(platforms: list[str], limit: int = 5) -> list[dict]:
    """Ask browser layer to scrape hackathon listings."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BROWSER_URL}/scrape",
            json={"platforms": platforms, "limit_per_platform": limit},
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            data = await resp.json()
            return data.get("hackathons", [])


async def call_browser_register(url: str, platform: str, dry_run: bool = False) -> bool:
    """Ask browser layer to register for a hackathon."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BROWSER_URL}/register",
            json={"url": url, "platform": platform, "dry_run": dry_run},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            data = await resp.json()
            return data.get("success", False)


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def run_scout(
    platforms: list[str] | None = None,
    min_score: int = 65,
    dry_run: bool = False,
) -> list[HackathonBrief]:
    from agents.python.infra.memory_keeper import MemoryKeeper

    platforms = platforms or ["devpost", "lablab", "devfolio"]
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    memory = MemoryKeeper()

    logger.info(f"[forge:scout] Scraping {platforms}...")
    raw_listings = await call_browser_scrape(platforms, limit=5)
    logger.info(f"[forge:scout] Scraped {len(raw_listings)} raw listings")

    # Convert to HackathonBrief objects
    briefs: list[HackathonBrief] = []
    for i, raw in enumerate(raw_listings):
        hackathon_id = f"{raw.get('platform', 'unknown')}-{i}-{int(datetime.now().timestamp())}"
        brief = HackathonBrief(
            hackathon_id=hackathon_id,
            name=raw.get("name", "Unknown"),
            url=raw.get("url", ""),
            platform=raw.get("platform", "devpost"),
            theme=raw.get("theme", ""),
            description=raw.get("description", ""),
            deadline=raw.get("deadline", ""),
            prizes=[Prize(**p) for p in raw.get("prizes", [])],
            judging_criteria=raw.get("judging_criteria", []),
            sponsor_techs=[SponsorTech(**s) for s in raw.get("sponsor_techs", [])],
            registration_open=raw.get("registration_open", True),
            total_participants=raw.get("participants"),
        )
        scored = await score_hackathon(brief)
        briefs.append(scored)

    # Sort by score, keep recommended
    briefs.sort(key=lambda b: b.score, reverse=True)
    qualified = [b for b in briefs if b.recommended]
    logger.info(f"[forge:scout] {len(qualified)}/{len(briefs)} qualify (score ≥ {min_score})")

    # Process top 3
    for brief in qualified[:3]:
        # Store in Redis + memory
        await redis.set(f"hackathon:{brief.hackathon_id}:brief", brief.model_dump_json(), ex=604800)
        await memory.store_hackathon_brief(brief.hackathon_id, brief.model_dump())

        # Register
        if brief.registration_open:
            registered = await call_browser_register(brief.url, brief.platform, dry_run=dry_run)
            if registered and not dry_run:
                # Trigger commander to start hackathon workflow
                await redis.publish("commander:new_hackathon", json.dumps({
                    "hackathon_id": brief.hackathon_id,
                    "brief": brief.model_dump(),
                }))

        logger.info(f"[forge:scout] {brief.name}: score={brief.score}, registered={not dry_run and brief.registration_open}")

    await redis.aclose()
    return qualified


# ── Worker ─────────────────────────────────────────────────────────────────────

async def run_worker() -> None:
    logger.info("[forge:scout] Starting daily discovery worker")
    while True:
        try:
            await run_scout(dry_run=os.environ.get("DRY_RUN") == "true")
        except Exception as e:
            logger.error(f"[forge:scout] Discovery cycle failed: {e}", exc_info=True)
        # Run every 6 hours
        await asyncio.sleep(6 * 60 * 60)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    async def main():
        results = await run_scout(dry_run=args.dry_run)
        for b in results[:5]:
            print(f"  {b.score:3d}/100 — {b.name} ({b.days_until_deadline}d, ${sum(p.amount or 0 for p in b.prizes):,.0f})")

    asyncio.run(main())
