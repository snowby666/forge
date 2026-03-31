# -*- coding: utf-8 -*-
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


def _parse_prize_amount(text: str) -> float:
    """Extract a numeric dollar amount from strings like '$10,000', '10K', '$50k in prizes'."""
    import re
    text = text.replace(",", "").replace(" ", "").upper()
    m = re.search(r'\$?([\d.]+)\s*K', text)
    if m:
        return float(m.group(1)) * 1000
    m = re.search(r'\$?([\d.]+)\s*M', text)
    if m:
        return float(m.group(1)) * 1_000_000
    m = re.search(r'\$?([\d.]+)', text)
    if m:
        return float(m.group(1))
    return 0.0


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
    logger.info(
        f"[forge:scout] LLM theme score for '{brief.name[:40]}': "
        f"{theme_score.score}/20 — {theme_score.reasoning[:100]}"
    )

    brief.score = sum(breakdown.values())
    brief.score_breakdown = breakdown
    brief.recommended = brief.score >= 65  # default; overridden by run_scout's min_score
    return brief


async def call_browser_scrape(platforms: list[str], limit: int = 5) -> list[dict]:
    """
    Scrape hackathon listings.
    Primary: Crawl4AI native Python extraction (JS rendering, no Stagehand server needed).
    Fallback: Stagehand browser layer (TypeScript server on BROWSER_URL).
    """
    # Try Crawl4AI first — handles JS-rendered SPAs natively, zero extra process
    try:
        from config.web_search import scrape_hackathon_listings
        listings = await scrape_hackathon_listings(platforms, limit_per_platform=limit)
        if listings:
            logger.info(f"[forge:scout] Crawl4AI extracted {len(listings)} listings from {len(platforms)} platforms")
            for item in listings:
                logger.info(
                    f"[forge:scout]   raw: {item.get('title', item.get('name', '?'))[:60]} "
                    f"| {item.get('platform', '?')} "
                    f"| prize={item.get('prize_amount', item.get('prize', 'n/a'))} "
                    f"| url={item.get('url', '?')[:70]}"
                )
            return listings
        logger.info("[forge:scout] Crawl4AI returned 0 listings — trying Stagehand fallback")
    except Exception as e:
        logger.warning(f"[forge:scout] Crawl4AI scrape failed ({e}) — trying Stagehand")

    # Fallback: original Stagehand browser layer
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BROWSER_URL}/scrape",
                json={"platforms": platforms, "limit_per_platform": limit},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                data = await resp.json()
                listings = data.get("hackathons", [])
                logger.info(f"[forge:scout] Stagehand returned {len(listings)} listings")
                return listings
    except Exception as e:
        logger.warning(f"[forge:scout] Stagehand fallback also failed: {e}")
        return []


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
    return_all: bool = False,
) -> list[HackathonBrief] | tuple[list[HackathonBrief], list[HackathonBrief]]:
    from agents.python.infra.memory_keeper import MemoryKeeper

    platforms = platforms or ["devpost", "lablab", "devfolio"]
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    memory = MemoryKeeper()

    logger.info(f"[forge:scout] Scraping {platforms}...")
    raw_listings = await call_browser_scrape(platforms, limit=5)
    logger.info(f"[forge:scout] Scraped {len(raw_listings)} raw listings from {platforms}")

    # Convert to HackathonBrief objects
    # CSS extraction keys differ from Stagehand keys — normalize both
    briefs: list[HackathonBrief] = []
    skipped = 0
    for i, raw in enumerate(raw_listings):
        try:
            hackathon_id = f"{raw.get('platform', 'unknown')}-{i}-{int(datetime.now().timestamp())}"

            # Normalize field names: CSS uses title/tagline/prize_amount, Stagehand uses name/theme/prizes
            name = raw.get("name") or raw.get("title") or "Unknown"
            theme = raw.get("theme") or raw.get("tagline") or ""
            description = raw.get("description") or raw.get("tagline") or ""
            url = raw.get("url") or ""

            # Parse prizes: Stagehand sends structured list, CSS sends prize_amount string
            prizes: list[Prize] = []
            if raw.get("prizes") and isinstance(raw["prizes"], list):
                prizes = [Prize(**p) for p in raw["prizes"]]
            elif raw.get("prize_amount") or raw.get("prize"):
                prize_str = raw.get("prize_amount") or raw.get("prize") or ""
                amount = _parse_prize_amount(prize_str)
                if amount > 0:
                    prizes = [Prize(name="Total Prize", amount=amount)]

            # Parse participant count (CSS returns text like "1,234 participants")
            participants = raw.get("participants") or raw.get("total_participants")
            if isinstance(participants, str):
                participants = int("".join(c for c in participants if c.isdigit()) or "0") or None

            # Skip entries with no URL or raw markdown fallbacks
            if not url or url.startswith("http") is False and "raw_markdown" in raw:
                logger.debug(f"[forge:scout] Skipping raw markdown fallback for {raw.get('platform')}")
                skipped += 1
                continue

            brief = HackathonBrief(
                hackathon_id=hackathon_id,
                name=name,
                url=url,
                platform=raw.get("platform", "devpost"),
                theme=theme,
                description=description,
                deadline=raw.get("deadline", ""),
                prizes=prizes,
                judging_criteria=raw.get("judging_criteria", []),
                sponsor_techs=[SponsorTech(**s) for s in raw.get("sponsor_techs", [])],
                registration_open=raw.get("registration_open", True),
                total_participants=participants,
            )
            scored = await score_hackathon(brief)
            briefs.append(scored)

            prize_total = sum(p.amount or 0 for p in scored.prizes)
            logger.info(
                f"[forge:scout] {scored.name[:50]:50s} "
                f"score={scored.score:3d}/100 "
                f"(prize={scored.score_breakdown.get('prize_pool', 0)} "
                f"sponsor={scored.score_breakdown.get('sponsor_prizes', 0)} "
                f"deadline={scored.score_breakdown.get('deadline_buffer', 0)} "
                f"theme={scored.score_breakdown.get('theme_match', 0)} "
                f"comp={scored.score_breakdown.get('competition_size', 0)}) "
                f"${prize_total:,.0f} | {scored.days_until_deadline}d left"
            )

        except Exception as e:
            logger.warning(f"[forge:scout] Failed to process listing {i} ({raw.get('title', raw.get('name', '?'))}): {e}")
            skipped += 1
            continue

    # Sort by score, keep recommended
    briefs.sort(key=lambda b: b.score, reverse=True)
    qualified = [b for b in briefs if b.score >= min_score]
    logger.info(
        f"[forge:scout] Results: {len(raw_listings)} scraped → "
        f"{len(briefs)} scored ({skipped} skipped) → "
        f"{len(qualified)} qualify (score ≥ {min_score})"
    )

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
    if return_all:
        return qualified, briefs
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
