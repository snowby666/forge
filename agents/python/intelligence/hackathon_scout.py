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
from config.agents_config import ALL_AGENTS
from config.electronhub import complete_json
from config.redis_client import get_redis

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

    For Devpost: uses ForgeDevpostClient.get_hackathon_detail() (real HTML + LLM).
    For others: uses Crawl4AI for page content, then LLM for structured extraction.
    """
    logger.info(f"[forge:scout:deep] Scraping detail page: {brief.url}")

    # Devpost: use our custom client — scrapes /rules, /details/faq, main page in parallel
    if brief.platform == "devpost":
        try:
            from config.devpost import ForgeDevpostClient, DevpostHackathon
            async with ForgeDevpostClient() as client:
                dh = DevpostHackathon(
                    id=0, title=brief.name, url=brief.url,
                    open_state="open", themes=[], prize_amount_raw="",
                    prize_usd=0, registrations_count=0,
                    submission_period="", time_left="", location="",
                    thumbnail_url="", organization_name="",
                    featured=False, invite_only=False, invite_description="",
                    prizes_cash_count=0, prizes_other_count=0,
                    winners_announced=False, submission_gallery_url="",
                    start_submission_url="", managed_by_devpost=False,
                )
                dh = await client.enrich_hackathon(dh)

                if dh.description:
                    brief.description = dh.description
                if dh.rules:
                    brief.rules = dh.rules
                if dh.deadline_iso:
                    brief.deadline = dh.deadline_iso
                if dh.judging_criteria:
                    brief.judging_criteria = dh.judging_criteria
                if dh.faqs:
                    brief.faqs = dh.faqs
                if dh.allowed_techs:
                    brief.allowed_techs = dh.allowed_techs
                brief.team_size_min = dh.team_size_min
                brief.team_size_max = dh.team_size_max

                # Replace Phase 1 placeholder prizes with detailed LLM-extracted ones
                if dh.prizes:
                    brief.prizes = []
                    for p in dh.prizes:
                        try:
                            amt = p.get("amount", 0)
                            if isinstance(amt, str):
                                amt = _parse_prize_amount(amt)
                            brief.prizes.append(Prize(
                                name=p.get("name", "Prize"),
                                amount=float(amt) if amt else None,
                                sponsor=p.get("sponsor"),
                            ))
                        except Exception:
                            continue

                for j in dh.judges:
                    try:
                        brief.judges.append(JudgeInfo(
                            name=j.get("name", ""),
                            title=j.get("title", ""),
                            company=j.get("company", ""),
                        ))
                    except Exception:
                        continue

                for t in dh.tracks:
                    try:
                        brief.tracks.append(TrackInfo(
                            name=t.get("name", ""),
                            description=t.get("description", ""),
                            sponsor=t.get("sponsor", ""),
                        ))
                    except Exception:
                        continue

                for s in dh.sponsors:
                    try:
                        brief.sponsor_techs.append(SponsorTech(
                            sponsor=s.get("name", ""),
                            api_name=s.get("api_name", ""),
                            docs_url=s.get("docs_url"),
                        ))
                    except Exception:
                        continue

                for cl in dh.community_links:
                    try:
                        brief.community_links.append(CommunityLink(
                            platform=cl.get("platform", "other"),
                            url=cl.get("url", ""),
                        ))
                    except Exception:
                        continue

                for r in dh.resources:
                    try:
                        brief.community_links.append(CommunityLink(
                            platform="resource",
                            url=r.get("url", ""),
                        ))
                    except Exception:
                        continue

                if dh.eligibility:
                    brief.rules = f"{brief.rules}\n\nEligibility: {dh.eligibility}".strip()

                brief.deep_scraped = True
                logger.info(
                    f"[forge:scout:deep] {brief.name}: "
                    f"{len(brief.prizes)} prizes, {len(brief.tracks)} tracks, "
                    f"{len(brief.judges)} judges, {len(brief.sponsor_techs)} sponsors"
                )
                return brief

        except Exception as e:
            logger.warning(f"[forge:scout:deep] Devpost client failed, falling back to generic: {e}")

    # Generic path: Crawl4AI fetch + LLM extraction
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

COMMUNITY_PATTERNS = {
    "discord": re.compile(r"discord\.(gg|com)", re.I),
    "reddit": re.compile(r"reddit\.com", re.I),
    "twitter": re.compile(r"(twitter|x)\.com", re.I),
    "slack": re.compile(r"slack\.(com|to)", re.I),
    "telegram": re.compile(r"t\.me", re.I),
    "youtube": re.compile(r"youtube\.com|youtu\.be", re.I),
    "github": re.compile(r"github\.com", re.I),
    "blog": re.compile(r"medium\.com|dev\.to|hashnode|substack", re.I),
}


async def _fast_search(query: str, max_results: int = 10) -> list[dict]:
    """
    Race all available search providers concurrently — first success wins.

    Uses asyncio.wait(FIRST_COMPLETED) with a hard wall-clock deadline.
    IMPORTANT: does NOT use asyncio.wait_for inside the race — wait_for
    blocks on cancellation of aiohttp cleanup (waits for server).
    asyncio.wait returns immediately on timeout regardless of task state.

    Returns list of {"title": ..., "url": ...} dicts.
    """
    import time as _time
    from config.web_search import (
        _search_serper, _search_tavily, _search_brave,
        _search_searxng, _search_firecrawl, _search_agentpick,
    )

    def _to_dicts(results: list) -> list[dict]:
        return [{"title": r.title, "url": r.url} for r in results if r.url]

    providers: list[tuple[str, Any]] = []
    if os.environ.get("SERPER_API_KEY", "").strip():
        providers.append(("serper", _search_serper(query, max_results)))
    if os.environ.get("TAVILY_API_KEYS") or os.environ.get("TAVILY_API_KEY", "").strip():
        providers.append(("tavily", _search_tavily(query, max_results)))
    if os.environ.get("BRAVE_SEARCH_API_KEY", "").strip():
        providers.append(("brave", _search_brave(query, max_results)))
    if os.environ.get("AGENTPICK_API_KEY", "").strip():
        providers.append(("agentpick", _search_agentpick(query, max_results)))
    if os.environ.get("FIRECRAWL_API_KEY", "").strip():
        providers.append(("firecrawl", _search_firecrawl(query, max_results)))
    if os.environ.get("SEARXNG_URL", "").strip():
        providers.append(("searxng", _search_searxng(query, max_results)))

    provider_names = [n for n, _ in providers]
    logger.info(f"[forge:scout:search] Racing {len(providers)} providers [{', '.join(provider_names)}] for '{query[:50]}'")
    t_start = _time.monotonic()
    DEADLINE = 8.0

    task_to_name: dict[asyncio.Task, str] = {}
    for name, coro in providers:
        task_to_name[asyncio.create_task(coro, name=name)] = name

    try:
        remaining = set(task_to_name.keys())
        while remaining:
            elapsed = _time.monotonic() - t_start
            time_left = DEADLINE - elapsed
            if time_left <= 0:
                logger.warning(f"[forge:scout:search] Deadline {DEADLINE}s hit after {elapsed*1000:.0f}ms")
                break

            done, remaining = await asyncio.wait(
                remaining, timeout=time_left, return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                logger.warning(f"[forge:scout:search] Deadline {DEADLINE}s — no providers responded")
                break

            for task in done:
                name = task_to_name[task]
                task_ms = (_time.monotonic() - t_start) * 1000
                try:
                    result = task.result()
                    dicts = _to_dicts(result) if result else []
                except asyncio.CancelledError:
                    logger.info(f"[forge:scout:search]   {name}: cancelled at {task_ms:.0f}ms")
                    continue
                except Exception as e:
                    logger.warning(f"[forge:scout:search]   {name}: ERROR at {task_ms:.0f}ms — {e}")
                    continue

                if dicts:
                    cancelled = [task_to_name[t] for t in remaining]
                    logger.info(
                        f"[forge:scout:search] Winner: {name} ({len(dicts)} results, {task_ms:.0f}ms)"
                        + (f" — cancelling [{', '.join(cancelled)}]" if cancelled else "")
                    )
                    for t in remaining:
                        t.cancel()
                    return dicts
                else:
                    logger.info(f"[forge:scout:search]   {name}: 0 results at {task_ms:.0f}ms")
    finally:
        for t in task_to_name:
            if not t.done():
                t.cancel()

    total_ms = (_time.monotonic() - t_start) * 1000
    logger.warning(f"[forge:scout:search] All {len(providers)} providers returned empty in {total_ms:.0f}ms")
    return []


async def discover_community(brief: HackathonBrief) -> HackathonBrief:
    """
    Find community links (Discord, Reddit, etc.) for a hackathon.

    Strategy (fast path first):
      1. Links already extracted from HTML in Phase 2 — free, instant
      2. _fast_search races all configured providers (Serper/Tavily/Brave/SearXNG)
    """
    known_urls = {cl.url for cl in brief.community_links}
    query = f'"{brief.name}" discord OR reddit OR slack OR github OR twitter'
    logger.info(f"[forge:scout:community] {brief.name[:40]}: searching ({len(known_urls)} links from HTML)")

    results = await _fast_search(query, max_results=15)
    if results:
        logger.info(f"[forge:scout:community]   search: {len(results)} results")
    else:
        logger.info(f"[forge:scout:community]   no search results found")

    new_links = 0
    for r in results:
        url = r.get("url", "")
        if url in known_urls:
            continue
        for platform, pattern in COMMUNITY_PATTERNS.items():
            if pattern.search(url):
                brief.community_links.append(CommunityLink(
                    platform=platform, url=url, description=r.get("title", "")[:120],
                ))
                known_urls.add(url)
                new_links += 1
                logger.info(f"[forge:scout:community]   + [{platform}] {url[:80]}")
                break

    logger.info(
        f"[forge:scout:community] {brief.name[:40]}: "
        f"+{new_links} new ({len(brief.community_links)} total)"
    )
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

    # Devpost: analyze past winners — but only if gallery likely has submissions
    # (open hackathons usually have empty galleries, skip to save time)
    raw = brief._raw_listing if hasattr(brief, '_raw_listing') else {}  # type: ignore[attr-defined]
    has_submissions = raw.get("open_state") == "ended" or raw.get("winners_announced")
    if brief.platform == "devpost" and brief.url and has_submissions:
        try:
            from config.devpost import ForgeDevpostClient
            async with ForgeDevpostClient() as client:
                from urllib.parse import urlparse
                parsed = urlparse(brief.url)
                slug = parsed.netloc.replace(".devpost.com", "") if "devpost.com" in parsed.netloc else ""
                if slug:
                    logger.info(f"[forge:scout:research] Analyzing past winners from {slug}.devpost.com")
                    analysis = await asyncio.wait_for(
                        client.get_past_winners(slug, pages=1, include_github=True),
                        timeout=45.0,
                    )
                    if analysis.projects:
                        for proj in analysis.projects[:5]:
                            brief.research.append(ResearchItem(
                                title=f"Past project: {proj.name}",
                                url=proj.url,
                                source="devpost",
                                relevance=proj.tagline or f"Tags: {', '.join(proj.tags[:5])}",
                                snippet=proj.description[:200] if proj.description else "",
                            ))
                        if analysis.tech_stack_frequency:
                            top_tech = list(analysis.tech_stack_frequency.keys())[:10]
                            brief.research.append(ResearchItem(
                                title=f"Common tech in past winners: {', '.join(top_tech)}",
                                url=brief.url,
                                source="analysis",
                                relevance=f"Top languages: {', '.join(list(analysis.github_languages.keys())[:5])}",
                            ))
                        logger.info(
                            f"[forge:scout:research] Past winners: {len(analysis.projects)} projects, "
                            f"top tech: {', '.join(list(analysis.tech_stack_frequency.keys())[:5])}"
                        )
        except asyncio.TimeoutError:
            logger.warning(f"[forge:scout:research] Past winner analysis timed out for {brief.name}")
        except Exception as e:
            logger.debug(f"[forge:scout:research] Past winner analysis failed: {e}")
    elif brief.platform == "devpost":
        logger.debug(f"[forge:scout:research] Skipping past winners for open hackathon {brief.name}")

    if brief.platform == "devfolio":
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

    # Tavily Deep Research: single call that does multi-query analysis
    has_tavily = bool(os.environ.get("TAVILY_API_KEYS") or os.environ.get("TAVILY_API_KEY", "").strip())
    tavily_research_done = False
    if has_tavily:
        try:
            from config.web_search import tavily_research
            research_query = (
                f"Research for hackathon '{brief.name}': "
                f"theme={brief.theme or 'general'}. "
                f"Find: 1) relevant arxiv papers, 2) GitHub repos/starter kits, "
                f"3) tutorials and frameworks, 4) winning strategies for similar hackathons. "
                f"Technologies: {', '.join(s.api_name for s in brief.sponsor_techs[:3]) or 'any AI/ML'}"
            )
            report = await asyncio.wait_for(tavily_research(research_query, model="mini"), timeout=60.0)
            if report and len(report) > 100:
                brief.research.append(ResearchItem(
                    title=f"Deep research report: {brief.name}",
                    url=brief.url or "",
                    source="tavily_research",
                    relevance=report[:500],
                    snippet=report[:2000],
                ))
                tavily_research_done = True
                logger.info(f"[forge:scout:research] Tavily research: {len(report)} chars for {brief.name[:40]}")
        except asyncio.TimeoutError:
            logger.warning(f"[forge:scout:research] Tavily research timed out for {brief.name[:40]}")
        except Exception as e:
            logger.debug(f"[forge:scout:research] Tavily research failed: {e}")

    # Fast search across all queries (Serper → Tavily → Brave → SearXNG)
    try:
        max_queries = 2 if tavily_research_done else 4
        search_tasks = [_fast_search(q, max_results=8) for q in queries[:max_queries]]
        results_batches = await asyncio.gather(*search_tasks, return_exceptions=True)

        known_urls = {r.url for r in brief.research}
        for batch in results_batches:
            if not isinstance(batch, list):
                continue
            for r in batch:
                url = r.get("url", "")
                title = r.get("title", "")
                if not url or url in known_urls:
                    continue

                source = "blog"
                if "arxiv" in url:
                    source = "arxiv"
                elif "github.com" in url:
                    source = "github"
                elif "docs." in url or "documentation" in url.lower():
                    source = "docs"
                elif "tutorial" in title.lower() or "guide" in title.lower():
                    source = "tutorial"

                brief.research.append(ResearchItem(
                    title=title[:150], url=url, source=source,
                    relevance=title[:200],
                ))
                known_urls.add(url)

        logger.info(
            f"[forge:scout:research] {brief.name[:40]}: "
            f"{len(brief.research)} items "
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
    days_left = 7  # fallback

    # Priority 1: use pre-parsed days_left from Devpost API
    raw = brief._raw_listing if hasattr(brief, '_raw_listing') else {}  # type: ignore[attr-defined]
    if raw.get("days_left") and isinstance(raw["days_left"], int) and raw["days_left"] > 0:
        days_left = raw["days_left"]
    else:
        # Priority 2: try ISO deadline from LLM extraction
        try:
            deadline = datetime.fromisoformat(brief.deadline.replace("Z", "+00:00"))
            days_left = max(0, (deadline - now).days)
        except Exception:
            # Priority 3: try parsing human-readable deadline like "Mar 31 - Apr 02, 2026"
            try:
                from dateutil.parser import parse as dateparse  # type: ignore[import-untyped]
                parts = brief.deadline.split(" - ")
                if len(parts) == 2:
                    end_date = dateparse(parts[1].strip())
                    days_left = max(0, (end_date - now.replace(tzinfo=None)).days)
                elif brief.deadline:
                    end_date = dateparse(brief.deadline)
                    days_left = max(0, (end_date - now.replace(tzinfo=None)).days)
            except Exception:
                pass

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
            10 if brief.total_participants < 300 else
            5 if brief.total_participants < 1000 else 2
        )

    # LLM theme scoring — use deep intel for richer context
    context_parts = []
    if brief.theme:
        context_parts.append(f"Theme: {brief.theme}")
    if brief.description:
        context_parts.append(f"Description: {brief.description[:600]}")
    if brief.judging_criteria:
        criteria = [c if isinstance(c, str) else c.get("name", str(c)) for c in brief.judging_criteria[:6]]
        context_parts.append(f"Judging: {', '.join(criteria)}")
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

    # Intelligence modifiers from API fields
    raw = brief._raw_listing if hasattr(brief, '_raw_listing') else {}
    if raw.get("featured"):
        breakdown["featured_bonus"] = 5
    if raw.get("invite_only"):
        breakdown["invite_only_penalty"] = -10

    # Prizes diversity: more cash prizes = more chances to win
    cash_count = raw.get("prizes_cash_count", 0)
    if isinstance(cash_count, int) and cash_count >= 3:
        breakdown["prize_diversity"] = 5
    elif isinstance(cash_count, int) and cash_count >= 2:
        breakdown["prize_diversity"] = 3

    brief.score = sum(breakdown.values())
    brief.score_breakdown = breakdown
    brief.recommended = brief.score >= 65
    return brief


# ── Platform Scraping ─────────────────────────────────────────────────────────

async def scrape_devpost_api(limit: int = 15) -> list[dict]:
    """
    Use Devpost's real JSON API — structured data, every field captured.
    Fetches ALL open hackathons (not just first page), then returns top N by prize.
    """
    try:
        from config.devpost import ForgeDevpostClient, _parse_time_left
        async with ForgeDevpostClient() as client:
            # Fetch all open hackathons across all pages
            hackathons = await client.list_hackathons(status="open", pages=8)

            # Filter out invite-only and winners-announced
            hackathons = [h for h in hackathons if not h.winners_announced]

            listings = []
            for h in hackathons[:limit]:
                days_left = _parse_time_left(h.time_left)
                listings.append({
                    "platform": "devpost",
                    "title": h.title,
                    "name": h.title,
                    "url": h.url,
                    "prize_amount": str(h.prize_usd),
                    "deadline": h.submission_period,
                    "participants": str(h.registrations_count) if h.registrations_count else None,
                    "theme": ", ".join(h.themes) if h.themes else "",
                    "tagline": ", ".join(h.themes[:3]) if h.themes else "",
                    "open_state": h.open_state,
                    "days_left": days_left,
                    "time_left": h.time_left,
                    # New intelligence fields
                    "organization": h.organization_name,
                    "featured": h.featured,
                    "invite_only": h.invite_only,
                    "invite_description": h.invite_description,
                    "prizes_cash_count": h.prizes_cash_count,
                    "prizes_other_count": h.prizes_other_count,
                    "submission_gallery_url": h.submission_gallery_url,
                    "start_submission_url": h.start_submission_url,
                    "location": h.location,
                    "_devpost_obj": h,
                })

            logger.info(f"[forge:scout] Devpost JSON API: {len(listings)}/{len(hackathons)} hackathons")
            for item in listings[:10]:
                logger.info(
                    f"[forge:scout]   devpost: {item['title'][:45]:45s} "
                    f"| ${float(item['prize_amount']):>8,.0f} "
                    f"| {item.get('participants', '?'):>5s} reg "
                    f"| {item.get('time_left', '?'):<20s} "
                    f"| {'★' if item.get('featured') else ' '} "
                    f"| {item['theme'][:30]}"
                )
            return listings
    except Exception as e:
        logger.warning(f"[forge:scout] Devpost JSON API failed: {e}")
        return []


async def scrape_other_platforms(platforms: list[str], limit: int = 5) -> list[dict]:
    """Crawl4AI / Stagehand / aiohttp scraping for non-Devpost platforms."""
    try:
        from config.web_search import scrape_hackathon_listings
        listings = await scrape_hackathon_listings(platforms, limit_per_platform=limit)
        if listings:
            logger.info(f"[forge:scout] Crawl4AI extracted {len(listings)} listings from {platforms}")
            for item in listings:
                logger.info(
                    f"[forge:scout]   raw: {item.get('title', item.get('name', '?'))[:60]} "
                    f"| {item.get('platform', '?')} "
                    f"| prize={item.get('prize_amount', item.get('prize', 'n/a'))} "
                    f"| url={item.get('url', '?')[:70]}"
                )
            return listings
        logger.info(f"[forge:scout] Crawl4AI returned 0 listings for {platforms}")
    except Exception as e:
        logger.warning(f"[forge:scout] Crawl4AI failed for {platforms}: {e}")

    # Stagehand fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BROWSER_URL}/scrape",
                json={"platforms": platforms, "limit_per_platform": limit},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                data = await resp.json()
                listings = data.get("hackathons", [])
                if listings:
                    logger.info(f"[forge:scout] Stagehand returned {len(listings)} listings for {platforms}")
                    return listings
    except Exception as e:
        logger.debug(f"[forge:scout] Stagehand not available: {e}")

    # Last resort: aiohttp fetch + regex extraction for known platforms
    logger.info(f"[forge:scout] Using aiohttp fallback for {platforms}")
    all_listings: list[dict] = []
    platform_urls = {
        "lablab": "https://lablab.ai/event",
        "devfolio": "https://devfolio.co/hackathons",
    }
    for plat in platforms:
        url = platform_urls.get(plat)
        if not url:
            continue
        try:
            from config.web_search import _fetch_fallback
            raw_html = await _fetch_fallback(url, max_chars=20000)
            if raw_html and len(raw_html) > 200:
                all_listings.append({
                    "platform": plat,
                    "raw_markdown": raw_html[:5000],
                    "url": url,
                    "title": f"{plat.title()} hackathon listings (raw)",
                })
                logger.info(f"[forge:scout] aiohttp fallback got {len(raw_html)} chars from {plat}")
        except Exception as e:
            logger.debug(f"[forge:scout] aiohttp fallback failed for {plat}: {e}")
    return all_listings


async def call_browser_scrape(platforms: list[str], limit: int = 5) -> list[dict]:
    """
    Scrape hackathon listings from all platforms.
    Devpost: uses real JSON API (structured, reliable).
    Others: Crawl4AI CSS extraction, Stagehand fallback.
    """
    tasks = []

    if "devpost" in platforms:
        tasks.append(scrape_devpost_api(limit=limit))

    other = [p for p in platforms if p != "devpost"]
    if other:
        tasks.append(scrape_other_platforms(other, limit=limit))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_listings: list[dict] = []
    for batch in results:
        if isinstance(batch, list):
            all_listings.extend(batch)
        elif isinstance(batch, Exception):
            logger.warning(f"[forge:scout] Platform scrape error: {batch}")

    logger.info(f"[forge:scout] Total: {len(all_listings)} listings from {platforms}")
    return all_listings


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
    redis = get_redis()
    memory = MemoryKeeper()

    # Load proxies for all network operations
    try:
        from config.proxy_manager import ensure_loaded, proxy_count
        await ensure_loaded()
        logger.info(f"[forge:scout] Proxy pool: {proxy_count()} proxies loaded")
    except Exception as e:
        logger.debug(f"[forge:scout] Proxies not available: {e}")

    # ── Phase 1: Discover ────────────────────────────────────────────────────
    logger.info(f"[forge:scout] ═══ Phase 1: DISCOVER — scraping {platforms} ═══")
    raw_listings = await call_browser_scrape(platforms, limit=20)
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
            brief._raw_listing = raw  # type: ignore[attr-defined]
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

    # ── Phase 2: Deep Scrape (parallel, batched to avoid flooding LLM) ──────
    if deep:
        logger.info(f"[forge:scout] ═══ Phase 2: DEEP SCRAPE — extracting detail pages ═══")
        BATCH_SIZE = 20
        all_deep: list[HackathonBrief] = []
        for batch_start in range(0, len(briefs), BATCH_SIZE):
            batch = briefs[batch_start:batch_start + BATCH_SIZE]
            logger.info(f"[forge:scout] Deep scrape batch {batch_start // BATCH_SIZE + 1} ({len(batch)} hackathons)")
            try:
                deep_tasks = [asyncio.wait_for(deep_scrape_hackathon(b), timeout=60.0) for b in batch]
                results = await asyncio.gather(*deep_tasks, return_exceptions=True)
                for idx, r in enumerate(results):
                    if isinstance(r, HackathonBrief):
                        all_deep.append(r)
                    else:
                        # Keep the original brief even if deep scrape failed
                        logger.warning(f"[forge:scout] Deep scrape failed for {batch[idx].name[:40]}: {r}")
                        all_deep.append(batch[idx])
            except Exception as e:
                logger.warning(f"[forge:scout] Deep scrape batch failed: {e}")
                all_deep.extend(batch)
        briefs = all_deep if all_deep else briefs
        logger.info(f"[forge:scout] Phase 2 complete: {sum(1 for b in briefs if b.deep_scraped)}/{len(briefs)} deep-scraped")

    # ── Phase 5: Score (before community/research so we can prioritize) ─────
    logger.info(f"[forge:scout] ═══ Phase 5: SCORE — evaluating all hackathons ═══")
    SCORE_BATCH = 20
    scored_briefs: list[HackathonBrief] = []
    for batch_start in range(0, len(briefs), SCORE_BATCH):
        batch = briefs[batch_start:batch_start + SCORE_BATCH]
        logger.info(f"[forge:scout] Score batch {batch_start // SCORE_BATCH + 1} ({len(batch)} hackathons)")
        score_tasks = [asyncio.wait_for(score_hackathon(b), timeout=30.0) for b in batch]
        results = await asyncio.gather(*score_tasks, return_exceptions=True)
        for idx, r in enumerate(results):
            if isinstance(r, HackathonBrief):
                scored_briefs.append(r)
                prize_total = sum(p.amount or 0 for p in r.prizes)
                bd = r.score_breakdown
                extras = []
                if bd.get("featured_bonus"):
                    extras.append(f"feat=+{bd['featured_bonus']}")
                if bd.get("invite_only_penalty"):
                    extras.append(f"invite={bd['invite_only_penalty']}")
                if bd.get("prize_diversity"):
                    extras.append(f"div=+{bd['prize_diversity']}")
                extra_str = f" | {' '.join(extras)}" if extras else ""
                logger.info(
                    f"[forge:scout] {r.name[:45]:45s} "
                    f"score={r.score:3d}/100 "
                    f"(prize={bd.get('prize_pool', 0)} "
                    f"sponsor={bd.get('sponsor_prizes', 0)} "
                    f"deadline={bd.get('deadline_buffer', 0)} "
                    f"theme={bd.get('theme_match', 0)} "
                    f"comp={bd.get('competition_size', 0)})"
                    f"{extra_str} "
                    f"${prize_total:,.0f} | {r.days_until_deadline}d left"
                )
            else:
                logger.warning(f"[forge:scout] Scoring failed for {batch[idx].name}: {r}")
                batch[idx].score = 0
                scored_briefs.append(batch[idx])

    briefs = scored_briefs
    briefs.sort(key=lambda b: b.score, reverse=True)
    qualified = [b for b in briefs if b.score >= min_score]

    # ── Phase 3 & 4: Community + Research (only for top candidates) ──────────
    if deep:
        top_for_deep = briefs[:5]

        # Phase 3: Community — per-hackathon 15s timeout, 30s global
        logger.info(f"[forge:scout] ═══ Phase 3: COMMUNITY INTEL — searching {len(top_for_deep)} hackathons ═══")
        try:
            community_tasks = [
                asyncio.wait_for(discover_community(b), timeout=15.0)
                for b in top_for_deep
            ]
            results = await asyncio.wait_for(
                asyncio.gather(*community_tasks, return_exceptions=True), timeout=30.0,
            )
            enriched = []
            for idx, r in enumerate(results):
                if isinstance(r, HackathonBrief):
                    enriched.append(r)
                else:
                    logger.warning(f"[forge:scout] Community failed for {top_for_deep[idx].name[:40]}: {r}")
                    enriched.append(top_for_deep[idx])
            top_for_deep = enriched
            logger.info(f"[forge:scout] Phase 3 complete: {len(top_for_deep)} enriched")
        except asyncio.TimeoutError:
            logger.warning("[forge:scout] Phase 3 TIMED OUT (30s) — continuing with what we have")

        # Phase 4: Research — per-hackathon 20s timeout, 45s global
        logger.info(f"[forge:scout] ═══ Phase 4: RESEARCH — finding papers/repos/tutorials ═══")
        try:
            research_tasks = [
                asyncio.wait_for(research_hackathon(b), timeout=20.0)
                for b in top_for_deep
            ]
            results = await asyncio.wait_for(
                asyncio.gather(*research_tasks, return_exceptions=True), timeout=45.0,
            )
            enriched = []
            for idx, r in enumerate(results):
                if isinstance(r, HackathonBrief):
                    enriched.append(r)
                else:
                    logger.warning(f"[forge:scout] Research failed for {top_for_deep[idx].name[:40]}: {r}")
                    enriched.append(top_for_deep[idx])
            top_for_deep = enriched
            logger.info(f"[forge:scout] Phase 4 complete: {len(top_for_deep)} researched")
        except asyncio.TimeoutError:
            logger.warning("[forge:scout] Phase 4 TIMED OUT (45s) — continuing with what we have")

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

    # ── Dedup: check which hackathon URLs are already tracked in Redis ──
    existing_keys = await redis.keys("hackathon:*:brief")
    existing_urls: set[str] = set()
    if existing_keys:
        raw_briefs = await asyncio.gather(*(redis.get(k) for k in existing_keys))
        for raw_brief in raw_briefs:
            if raw_brief:
                try:
                    existing_urls.add(json.loads(raw_brief).get("url", ""))
                except Exception:
                    pass

    new_qualified: list[HackathonBrief] = []
    for brief in qualified:
        if brief.url in existing_urls:
            logger.info(f"[forge:scout] Skipping duplicate: {brief.name} ({brief.url})")
            continue
        new_qualified.append(brief)
        existing_urls.add(brief.url)

    if len(qualified) != len(new_qualified):
        logger.info(
            f"[forge:scout] Dedup: {len(qualified)} qualified → {len(new_qualified)} new "
            f"({len(qualified) - len(new_qualified)} already tracked)"
        )

    # Process top 3 NEW qualified
    for brief in new_qualified[:3]:
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
