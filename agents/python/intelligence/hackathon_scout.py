# -*- coding: utf-8 -*-
"""
Hackathon Scout Agent — Deep Intelligence Edition
==================================================
Layer 1 — Intelligence. Runs first, in parallel with other intel agents.

Multi-phase adaptive scout:
  Phase 1: DISCOVER — Scrape listing pages (Devpost, Lablab, Devfolio)
  Phase 2: DEEP SCRAPE — Visit each hackathon detail page, extract everything
  Phase 3: COMMUNITY INTEL — Find Discord, Reddit, Twitter, blog posts
  Phase 4: RESEARCH — Search for related papers, frameworks, repos
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from config.electronhub import complete, complete_json
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


class CommunityLink(BaseModel):
    platform: str       # discord | reddit | twitter | slack | telegram | blog | youtube | github
    url: str
    description: str = ""
    member_count: int | None = None


class ResearchItem(BaseModel):
    title: str
    url: str
    source: str         # arxiv | github | blog | docs | tutorial
    relevance: str      # one-line why this matters
    snippet: str = ""


class JudgeInfo(BaseModel):
    name: str
    title: str = ""
    company: str = ""
    linkedin: str = ""
    expertise: list[str] = Field(default_factory=list)


class TrackInfo(BaseModel):
    name: str
    description: str = ""
    prizes: list[Prize] = Field(default_factory=list)
    sponsor: str = ""


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
    # Deep intel fields
    rules: str = ""
    tracks: list[TrackInfo] = Field(default_factory=list)
    judges: list[JudgeInfo] = Field(default_factory=list)
    faqs: list[str] = Field(default_factory=list)
    allowed_techs: list[str] = Field(default_factory=list)
    community_links: list[CommunityLink] = Field(default_factory=list)
    research: list[ResearchItem] = Field(default_factory=list)
    related_hackathons: list[str] = Field(default_factory=list)
    deep_scraped: bool = False
    # Scoring
    score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    days_until_deadline: int = 0
    recommended: bool = False


class ThemeScore(BaseModel):
    score: int          # 0–20
    reasoning: str


class DeepPageExtraction(BaseModel):
    """LLM-extracted structured data from a hackathon detail page."""
    description: str = ""
    theme: str = ""
    rules: str = ""
    deadline: str = ""
    prizes: list[dict] = Field(default_factory=list)
    tracks: list[dict] = Field(default_factory=list)
    judges: list[dict] = Field(default_factory=list)
    judging_criteria: list[str] = Field(default_factory=list)
    sponsor_techs: list[dict] = Field(default_factory=list)
    faqs: list[str] = Field(default_factory=list)
    allowed_techs: list[str] = Field(default_factory=list)
    community_links: list[dict] = Field(default_factory=list)
    team_size_min: int = 1
    team_size_max: int = 5
    total_participants: int | None = None
    registration_open: bool = True


# ── Utilities ─────────────────────────────────────────────────────────────────

def _parse_prize_amount(text: str) -> float:
    """Extract a numeric dollar amount from strings like '$10,000', '10K', '$50k in prizes'."""
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


# ── Phase 2: Deep Scrape ─────────────────────────────────────────────────────

async def deep_scrape_hackathon(brief: HackathonBrief) -> HackathonBrief:
    """
    Visit the hackathon's detail page and extract EVERYTHING:
    rules, prizes, judges, tracks, sponsors, FAQs, community links, tech stack.
    Uses Crawl4AI for page content, then LLM for structured extraction.
    """
    logger.info(f"[forge:scout:deep] Scraping detail page: {brief.url}")

    page_content = ""
    try:
        from config.web_search import fetch_full_content
        page_content = await fetch_full_content(brief.url, max_chars=12000)
    except Exception as e:
        logger.warning(f"[forge:scout:deep] fetch_full_content failed for {brief.url}: {e}")

    if not page_content or len(page_content) < 100:
        logger.info(f"[forge:scout:deep] No content from detail page, trying adaptive crawl")
        try:
            from config.web_search import adaptive_crawl
            pages = await adaptive_crawl(
                start_url=brief.url,
                query=f"{brief.name} hackathon rules prizes judges sponsors",
                max_pages=5,
            )
            if pages:
                page_content = "\n\n---\n\n".join(
                    p.get("content", "")[:4000] for p in pages[:3]
                )
        except Exception as e:
            logger.warning(f"[forge:scout:deep] adaptive_crawl failed: {e}")

    if not page_content or len(page_content) < 50:
        logger.info(f"[forge:scout:deep] Could not scrape detail page for {brief.name}")
        return brief

    # LLM extraction from page content
    try:
        extraction = await complete_json(
            task="scout-hackathons",
            response_model=DeepPageExtraction,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract ALL hackathon information from this page. Be thorough.\n\n"
                    f"Page content:\n{page_content[:10000]}\n\n"
                    f"For prizes: include name, amount (numeric USD), sponsor if any.\n"
                    f"For judges: include name, title, company.\n"
                    f"For tracks: include name, description, sponsor, prize amount.\n"
                    f"For community_links: include platform (discord/reddit/twitter/slack/telegram/blog/youtube/github), url.\n"
                    f"For sponsor_techs: include sponsor name, api_name, docs_url if found.\n"
                    f"deadline should be ISO 8601 format if possible.\n"
                    f"Extract registration status, team size limits, participant count."
                ),
            }],
            temperature=0.1,
        )

        # Merge extracted data into the brief (don't overwrite good data with empty)
        if extraction.description and len(extraction.description) > len(brief.description):
            brief.description = extraction.description
        if extraction.theme and (not brief.theme or len(extraction.theme) > len(brief.theme)):
            brief.theme = extraction.theme
        if extraction.rules:
            brief.rules = extraction.rules
        if extraction.deadline and not brief.deadline:
            brief.deadline = extraction.deadline
        if extraction.judging_criteria:
            brief.judging_criteria = extraction.judging_criteria
        if extraction.faqs:
            brief.faqs = extraction.faqs
        if extraction.allowed_techs:
            brief.allowed_techs = extraction.allowed_techs
        brief.team_size_min = extraction.team_size_min
        brief.team_size_max = extraction.team_size_max
        if extraction.total_participants:
            brief.total_participants = extraction.total_participants
        brief.registration_open = extraction.registration_open

        # Merge prizes (prefer deep-scraped if more detailed)
        if extraction.prizes:
            deep_prizes = []
            for p in extraction.prizes:
                try:
                    amount = p.get("amount")
                    if isinstance(amount, str):
                        amount = _parse_prize_amount(amount)
                    deep_prizes.append(Prize(
                        name=p.get("name", "Prize"),
                        amount=float(amount) if amount else None,
                        sponsor=p.get("sponsor"),
                        requirements=p.get("requirements"),
                    ))
                except Exception:
                    continue
            if len(deep_prizes) >= len(brief.prizes):
                brief.prizes = deep_prizes

        # Merge tracks
        if extraction.tracks:
            for t in extraction.tracks:
                try:
                    track_prizes = []
                    for tp in t.get("prizes", []):
                        amt = tp.get("amount")
                        if isinstance(amt, str):
                            amt = _parse_prize_amount(amt)
                        track_prizes.append(Prize(
                            name=tp.get("name", "Track Prize"),
                            amount=float(amt) if amt else None,
                            sponsor=tp.get("sponsor"),
                        ))
                    brief.tracks.append(TrackInfo(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        prizes=track_prizes,
                        sponsor=t.get("sponsor", ""),
                    ))
                except Exception:
                    continue

        # Merge judges
        if extraction.judges:
            for j in extraction.judges:
                try:
                    brief.judges.append(JudgeInfo(
                        name=j.get("name", ""),
                        title=j.get("title", ""),
                        company=j.get("company", ""),
                        linkedin=j.get("linkedin", ""),
                        expertise=j.get("expertise", []),
                    ))
                except Exception:
                    continue

        # Merge sponsor techs
        if extraction.sponsor_techs:
            for s in extraction.sponsor_techs:
                try:
                    brief.sponsor_techs.append(SponsorTech(
                        sponsor=s.get("sponsor", ""),
                        api_name=s.get("api_name", ""),
                        docs_url=s.get("docs_url"),
                        prize_amount=float(s.get("prize_amount", 0)) if s.get("prize_amount") else None,
                    ))
                except Exception:
                    continue

        # Merge community links found on the page
        if extraction.community_links:
            for cl in extraction.community_links:
                try:
                    brief.community_links.append(CommunityLink(
                        platform=cl.get("platform", "other"),
                        url=cl.get("url", ""),
                        description=cl.get("description", ""),
                    ))
                except Exception:
                    continue

        brief.deep_scraped = True
        logger.info(
            f"[forge:scout:deep] {brief.name}: "
            f"{len(brief.prizes)} prizes, {len(brief.tracks)} tracks, "
            f"{len(brief.judges)} judges, {len(brief.sponsor_techs)} sponsors, "
            f"{len(brief.community_links)} community links, "
            f"{len(brief.judging_criteria)} judging criteria"
        )

    except Exception as e:
        logger.warning(f"[forge:scout:deep] LLM extraction failed for {brief.name}: {e}")

    return brief


# ── Phase 3: Community Intel ──────────────────────────────────────────────────

async def discover_community(brief: HackathonBrief) -> HackathonBrief:
    """
    Search the web for Discord, Reddit, Twitter, Slack, GitHub, blog posts
    related to this hackathon. Builds the community_links list.
    """
    logger.info(f"[forge:scout:community] Searching for community around: {brief.name}")

    # Already found some links from the detail page — track URLs to avoid dupes
    known_urls = {cl.url for cl in brief.community_links}

    search_queries = [
        f'"{brief.name}" discord OR reddit OR slack OR telegram',
        f'"{brief.name}" hackathon twitter OR blog OR announcement',
        f'"{brief.name}" github OR devpost OR youtube',
    ]

    try:
        from config.web_search import web_search, SearchResult

        tasks = [web_search(q, max_results=5) for q in search_queries]
        results_batches = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[SearchResult] = []
        for batch in results_batches:
            if isinstance(batch, list):
                all_results.extend(batch)

        platform_patterns = {
            "discord": r"discord\.(gg|com)",
            "reddit": r"reddit\.com",
            "twitter": r"(twitter|x)\.com",
            "slack": r"slack\.(com|to)",
            "telegram": r"t\.me",
            "youtube": r"youtube\.com|youtu\.be",
            "github": r"github\.com",
            "blog": r"medium\.com|dev\.to|hashnode|substack",
        }

        for result in all_results:
            if result.url in known_urls:
                continue
            for platform, pattern in platform_patterns.items():
                if re.search(pattern, result.url, re.I):
                    brief.community_links.append(CommunityLink(
                        platform=platform,
                        url=result.url,
                        description=result.title[:120],
                    ))
                    known_urls.add(result.url)
                    break

        logger.info(
            f"[forge:scout:community] {brief.name}: "
            f"found {len(brief.community_links)} community links total"
        )

    except Exception as e:
        logger.warning(f"[forge:scout:community] Search failed for {brief.name}: {e}")

    return brief


# ── Phase 4: Research ─────────────────────────────────────────────────────────

async def research_hackathon(brief: HackathonBrief) -> HackathonBrief:
    """
    Search for papers, frameworks, repos, and prior winning projects
    relevant to this hackathon's theme and sponsor technologies.
    """
    logger.info(f"[forge:scout:research] Researching theme and tech for: {brief.name}")

    # Build targeted search queries based on extracted intel
    queries = []

    if brief.theme:
        queries.append(f"{brief.theme} AI agent framework tutorial 2025 OR 2026")
        queries.append(f"{brief.theme} arxiv paper machine learning")

    for sponsor in brief.sponsor_techs[:3]:
        queries.append(f"{sponsor.sponsor} {sponsor.api_name} API tutorial hackathon")

    # Search for past winners on the same platform
    if brief.platform == "devpost":
        queries.append(f"site:devpost.com {brief.theme or brief.name} winner")
    elif brief.platform == "devfolio":
        queries.append(f"site:devfolio.co {brief.theme or brief.name} project")

    # Search for track-specific strategies
    for track in brief.tracks[:2]:
        if track.sponsor:
            queries.append(f"{track.sponsor} {track.name} hackathon project example")

    if not queries:
        queries = [
            f"{brief.name} hackathon project ideas winning strategy",
            f"{brief.name} hackathon tutorial getting started",
        ]

    try:
        from config.web_search import deep_search, SearchResult

        search_tasks = [deep_search(q, max_results=5, expand_queries=False, rerank=False) for q in queries[:6]]
        results_batches = await asyncio.gather(*search_tasks, return_exceptions=True)

        known_urls = {r.url for r in brief.research}
        for batch in results_batches:
            if isinstance(batch, Exception):
                continue
            results, stats = batch
            for result in results:
                if result.url in known_urls:
                    continue

                source = "blog"
                if "arxiv" in result.url:
                    source = "arxiv"
                elif "github.com" in result.url:
                    source = "github"
                elif "docs." in result.url or "documentation" in result.url.lower():
                    source = "docs"
                elif "tutorial" in result.title.lower() or "guide" in result.title.lower():
                    source = "tutorial"

                brief.research.append(ResearchItem(
                    title=result.title[:150],
                    url=result.url,
                    source=source,
                    relevance=result.snippet[:200],
                    snippet=result.snippet[:300],
                ))
                known_urls.add(result.url)

        logger.info(
            f"[forge:scout:research] {brief.name}: "
            f"found {len(brief.research)} research items "
            f"({sum(1 for r in brief.research if r.source == 'arxiv')} papers, "
            f"{sum(1 for r in brief.research if r.source == 'github')} repos, "
            f"{sum(1 for r in brief.research if r.source == 'docs')} docs)"
        )

    except Exception as e:
        logger.warning(f"[forge:scout:research] Research failed for {brief.name}: {e}")

    return brief


# ── Scoring ───────────────────────────────────────────────────────────────────

async def score_hackathon(brief: HackathonBrief) -> HackathonBrief:
    """Score a hackathon 0–100 using rule-based scoring + LLM theme analysis."""
    now = datetime.now(timezone.utc)
    try:
        deadline = datetime.fromisoformat(brief.deadline.replace("Z", "+00:00"))
        days_left = max(0, (deadline - now).days)
    except Exception:
        days_left = 7

    brief.days_until_deadline = days_left
    total_prize = sum(p.amount or 0 for p in brief.prizes)
    sponsor_prize_count = sum(1 for p in brief.prizes if p.sponsor)

    breakdown: dict[str, int] = {
        "prize_pool": (25 if total_prize >= 10_000 else 15 if total_prize >= 5_000 else 8 if total_prize >= 1_000 else 0),
        "sponsor_prizes": min(sponsor_prize_count * 7, 20),
        "deadline_buffer": (15 if days_left >= 10 else 10 if days_left >= 5 else 5 if days_left >= 3 else 0),
        "theme_match": 0,
        "competition_size": 15,
    }

    if brief.total_participants is not None:
        breakdown["competition_size"] = (
            20 if brief.total_participants < 100 else
            10 if brief.total_participants < 300 else 5
        )

    # LLM theme scoring — use deep intel for richer context
    context_parts = []
    if brief.theme:
        context_parts.append(f"Theme: {brief.theme}")
    if brief.description:
        context_parts.append(f"Description: {brief.description[:600]}")
    if brief.judging_criteria:
        context_parts.append(f"Judging: {', '.join(brief.judging_criteria[:6])}")
    if brief.tracks:
        track_names = [t.name for t in brief.tracks[:5]]
        context_parts.append(f"Tracks: {', '.join(track_names)}")
    if brief.sponsor_techs:
        sponsors = [f"{s.sponsor} ({s.api_name})" for s in brief.sponsor_techs[:5]]
        context_parts.append(f"Sponsor APIs: {', '.join(sponsors)}")
    if brief.allowed_techs:
        context_parts.append(f"Required/allowed tech: {', '.join(brief.allowed_techs[:10])}")

    theme_score = await complete_json(
        task="scout-hackathons",
        response_model=ThemeScore,
        messages=[{
            "role": "user",
            "content": (
                f"Score 0–20: How well does this hackathon suit an autonomous AI agent development team?\n\n"
                f"{chr(10).join(context_parts)}\n\n"
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
    brief.recommended = brief.score >= 65
    return brief


# ── Platform Scraping ─────────────────────────────────────────────────────────

async def call_browser_scrape(platforms: list[str], limit: int = 5) -> list[dict]:
    """
    Scrape hackathon listings.
    Primary: Crawl4AI native Python extraction.
    Fallback: Stagehand browser layer.
    """
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
    deep: bool = True,
) -> list[HackathonBrief] | tuple[list[HackathonBrief], list[HackathonBrief]]:
    """
    Full multi-phase scout pipeline.

    Phase 1: DISCOVER — scrape listing pages for hackathon URLs and basic info
    Phase 2: DEEP SCRAPE — visit each detail page, LLM-extract everything
    Phase 3: COMMUNITY — find Discord, Reddit, Twitter, blogs
    Phase 4: RESEARCH — find papers, repos, tutorials for the theme
    Phase 5: SCORE — rule-based + LLM scoring with deep context
    """
    from agents.python.infra.memory_keeper import MemoryKeeper

    platforms = platforms or ["devpost", "lablab", "devfolio"]
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    memory = MemoryKeeper()

    # ── Phase 1: Discover ────────────────────────────────────────────────────
    logger.info(f"[forge:scout] ═══ Phase 1: DISCOVER — scraping {platforms} ═══")
    raw_listings = await call_browser_scrape(platforms, limit=5)
    logger.info(f"[forge:scout] Discovered {len(raw_listings)} raw listings")

    # Convert to HackathonBrief objects
    briefs: list[HackathonBrief] = []
    skipped = 0
    for i, raw in enumerate(raw_listings):
        try:
            hackathon_id = f"{raw.get('platform', 'unknown')}-{i}-{int(datetime.now().timestamp())}"

            name = raw.get("name") or raw.get("title") or "Unknown"
            theme = raw.get("theme") or raw.get("tagline") or ""
            description = raw.get("description") or raw.get("tagline") or ""
            url = raw.get("url") or ""

            prizes: list[Prize] = []
            if raw.get("prizes") and isinstance(raw["prizes"], list):
                prizes = [Prize(**p) for p in raw["prizes"]]
            elif raw.get("prize_amount") or raw.get("prize"):
                prize_str = raw.get("prize_amount") or raw.get("prize") or ""
                amount = _parse_prize_amount(prize_str)
                if amount > 0:
                    prizes = [Prize(name="Total Prize", amount=amount)]

            participants = raw.get("participants") or raw.get("total_participants")
            if isinstance(participants, str):
                participants = int("".join(c for c in participants if c.isdigit()) or "0") or None

            if not url or (not url.startswith("http") and "raw_markdown" in raw):
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
            briefs.append(brief)
            logger.info(f"[forge:scout] #{i+1} {name[:60]} | {url[:70]}")

        except Exception as e:
            logger.warning(f"[forge:scout] Failed to parse listing {i} ({raw.get('title', raw.get('name', '?'))}): {e}")
            skipped += 1
            continue

    logger.info(f"[forge:scout] Phase 1 complete: {len(briefs)} hackathons parsed ({skipped} skipped)")

    if not briefs:
        logger.warning("[forge:scout] No hackathons found in Phase 1")
        await redis.aclose()
        if return_all:
            return [], []
        return []

    # ── Phase 2: Deep Scrape (parallel) ──────────────────────────────────────
    if deep:
        logger.info(f"[forge:scout] ═══ Phase 2: DEEP SCRAPE — extracting detail pages ═══")
        deep_tasks = [deep_scrape_hackathon(b) for b in briefs]
        briefs = list(await asyncio.gather(*deep_tasks, return_exceptions=False))
        # Filter out any that returned as exceptions
        briefs = [b for b in briefs if isinstance(b, HackathonBrief)]
        logger.info(f"[forge:scout] Phase 2 complete: {sum(1 for b in briefs if b.deep_scraped)}/{len(briefs)} deep-scraped")

    # ── Phase 5: Score (before community/research so we can prioritize) ─────
    logger.info(f"[forge:scout] ═══ Phase 5: SCORE — evaluating all hackathons ═══")
    scored_briefs = []
    for brief in briefs:
        try:
            scored = await score_hackathon(brief)
            scored_briefs.append(scored)

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
            logger.warning(f"[forge:scout] Scoring failed for {brief.name}: {e}")
            brief.score = 0
            scored_briefs.append(brief)

    briefs = scored_briefs
    briefs.sort(key=lambda b: b.score, reverse=True)
    qualified = [b for b in briefs if b.score >= min_score]

    # ── Phase 3 & 4: Community + Research (only for top candidates) ──────────
    if deep:
        top_for_deep = briefs[:5]  # research top 5 regardless of qualification
        logger.info(f"[forge:scout] ═══ Phase 3: COMMUNITY INTEL — searching {len(top_for_deep)} hackathons ═══")
        community_tasks = [discover_community(b) for b in top_for_deep]
        top_for_deep = list(await asyncio.gather(*community_tasks, return_exceptions=False))
        top_for_deep = [b for b in top_for_deep if isinstance(b, HackathonBrief)]

        logger.info(f"[forge:scout] ═══ Phase 4: RESEARCH — finding papers/repos/tutorials ═══")
        research_tasks = [research_hackathon(b) for b in top_for_deep]
        top_for_deep = list(await asyncio.gather(*research_tasks, return_exceptions=False))
        top_for_deep = [b for b in top_for_deep if isinstance(b, HackathonBrief)]

        # Merge enriched data back into briefs
        enriched_ids = {b.hackathon_id for b in top_for_deep}
        briefs = top_for_deep + [b for b in briefs if b.hackathon_id not in enriched_ids]
        briefs.sort(key=lambda b: b.score, reverse=True)
        qualified = [b for b in briefs if b.score >= min_score]

    logger.info(
        f"[forge:scout] ═══ RESULTS: {len(raw_listings)} scraped → "
        f"{len(briefs)} scored ({skipped} skipped) → "
        f"{len(qualified)} qualify (score ≥ {min_score}) ═══"
    )

    # Process top 3 qualified
    for brief in qualified[:3]:
        await redis.set(f"hackathon:{brief.hackathon_id}:brief", brief.model_dump_json(), ex=604800)
        await memory.store_hackathon_brief(brief.hackathon_id, brief.model_dump())

        if brief.registration_open:
            registered = await call_browser_register(brief.url, brief.platform, dry_run=dry_run)
            if registered and not dry_run:
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
        await asyncio.sleep(6 * 60 * 60)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--shallow", action="store_true", help="Skip deep scrape / research phases")
    args = parser.parse_args()

    async def main():
        results = await run_scout(dry_run=args.dry_run, deep=not args.shallow)
        for b in results[:5]:
            print(f"  {b.score:3d}/100 — {b.name} ({b.days_until_deadline}d, ${sum(p.amount or 0 for p in b.prizes):,.0f})")

    asyncio.run(main())
