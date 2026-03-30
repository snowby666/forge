"""
Intelligence Agents — Competitor Analyst, Judge Profiler, Sponsor Researcher
All run in parallel with Hackathon Scout after a hackathon is registered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import aiohttp
from pydantic import BaseModel
from redis.asyncio import Redis

from config.electronhub import complete_json, complete
from config.agents_config import ALL_AGENTS

logger = logging.getLogger(__name__)
BROWSER_URL = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")


# ─────────────────────────────────────────────────────────────────────────────
# COMPETITOR ANALYST
# ─────────────────────────────────────────────────────────────────────────────

class PastWinner(BaseModel):
    project_name: str
    hackathon: str
    year: int | None = None
    url: str | None = None
    problem_category: str
    tech_stack: list[str]
    why_it_won: str
    presentation_quality: str  # "high" | "medium" | "low"


class CompReport(BaseModel):
    hackathon_name: str
    top_winning_patterns: list[str]      # max 5 — specific and actionable
    overused_themes: list[str]           # avoid these
    underexplored_opportunities: list[str]  # gaps in the market
    common_failure_patterns: list[str]   # what loses
    past_winners: list[PastWinner]       # max 5 examples
    positioning_recommendation: str      # "Our project should be unique by ___"
    judge_aesthetic_preference: str      # inferred from past winners' visual quality


async def analyze_competitors(
    hackathon_id: str,
    brief: dict,
    redis: Redis,
) -> CompReport:
    AGENT = ALL_AGENTS["competitor_analyst"]

    # Scrape past winners from Devpost
    platform_url = brief.get("url", "")
    past_winners_data: list[dict] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BROWSER_URL}/scrape",
                json={
                    "platforms": [],
                    "custom_urls": [f"{platform_url}#winners", f"{platform_url}?tab=winners"],
                    "limit_per_platform": 5,
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
                past_winners_data = data.get("hackathons", [])
    except Exception as e:
        logger.warning(f"[forge:intel] Scraping past winners failed: {e}")

    report = await complete_json(
        task="analyze-competitors",
        response_model=CompReport,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Analyze the competitive landscape for this hackathon.

Hackathon: {brief.get('name')}
Theme: {brief.get('theme')}
Description: {brief.get('description', '')[:500]}
Judging criteria: {', '.join(brief.get('judging_criteria', []))}

Past winners/projects found on platform:
{json.dumps(past_winners_data[:5], indent=2)}

Provide:
1. Top 5 winning patterns from this hackathon and similar ones
2. Overused themes to avoid (be specific — not just "chatbots")
3. Underexplored opportunities (real gaps in what's been built)
4. Common failure patterns from past submissions
5. Specific positioning recommendation for differentiation""",
        }],
        temperature=0.3,
    )

    await redis.set(f"hackathon:{hackathon_id}:comp_report", report.model_dump_json(), ex=604800)
    logger.info(f"[forge:intel] Done. {len(report.top_winning_patterns)} patterns found, {len(report.overused_themes)} themes to avoid")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# JUDGE PROFILER
# ─────────────────────────────────────────────────────────────────────────────

class JudgeBackground(BaseModel):
    name: str
    title: str
    company: str | None = None
    background: str     # "engineering" | "design" | "product" | "vc" | "domain_expert"
    technical_depth: str  # "high" | "medium" | "low"
    known_interests: list[str]
    likely_care_about: list[str]


class JudgeProfile(BaseModel):
    judges: list[JudgeBackground]
    panel_character: str        # overall characterization of the panel
    resonance_factors: list[str]  # what WILL resonate with this specific panel
    anti_resonance_factors: list[str]  # what will NOT resonate
    recommended_language: str   # "technical" | "business" | "balanced"
    recommended_demo_depth: str  # how technical the demo/README should be
    narrative_framing: str      # how to frame the problem/solution for these judges


async def profile_judges(
    hackathon_id: str,
    brief: dict,
    redis: Redis,
) -> JudgeProfile:
    AGENT = ALL_AGENTS["judge_profiler"]

    # Scrape judges from hackathon page
    judges_raw: list[dict] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BROWSER_URL}/scrape",
                json={"custom_urls": [brief.get("url", "")], "extract_judges": True},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()
                judges_raw = data.get("judges", [])
    except Exception as e:
        logger.warning(f"[forge:intel] Scraping judges failed: {e}")

    profile = await complete_json(
        task="profile-judges",
        response_model=JudgeProfile,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Profile the judges for this hackathon.

Hackathon: {brief.get('name')}
Theme: {brief.get('theme')}

Judges found: {json.dumps(judges_raw, indent=2) if judges_raw else "Not scraped — infer from hackathon type and sponsors"}

Infer from context if judges not available:
- Enterprise hackathons → mostly senior engineers + product managers
- Startup hackathons → VCs + startup founders
- Domain hackathons (health, edu) → domain experts + technologists
- Big tech hackathons → senior engineers who care about technical depth

Provide actionable guidance on: what to emphasize, what language to use,
how technical the demo should be, what narrative framing will win this panel.""",
        }],
        temperature=0.3,
    )

    await redis.set(f"hackathon:{hackathon_id}:judge_profile", profile.model_dump_json(), ex=604800)
    logger.info(f"[forge:intel] Done. {len(profile.judges)} judges profiled, language={profile.recommended_language}")
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# SPONSOR RESEARCHER
# ─────────────────────────────────────────────────────────────────────────────

class SponsorOpportunity(BaseModel):
    sponsor: str
    api_name: str
    prize_amount: float
    prize_name: str
    docs_url: str
    sdk_available: bool
    integration_description: str   # the simplest integration that qualifies
    estimated_hours: float          # honest estimate (overestimate)
    ui_visibility: str              # how it appears in the UI to judges
    eligibility_requirements: list[str]
    gotchas: list[str]              # rate limits, approval delays, etc.
    value_score: float              # prize_amount / estimated_hours
    recommendation: str             # "high_priority" | "medium" | "skip"


class SponsorMap(BaseModel):
    hackathon_name: str
    opportunities: list[SponsorOpportunity]  # sorted by value_score desc
    total_potential_prize: float
    recommended_integrations: list[str]      # top 2-3 sponsor names
    integration_order: list[str]             # which to build first
    integration_timeline_hours: float        # total hours for all recommended
    badge_copy: dict[str, str]               # "Sponsor Name": "Powered by X" text


async def research_sponsors(
    hackathon_id: str,
    brief: dict,
    redis: Redis,
) -> SponsorMap:
    AGENT = ALL_AGENTS["sponsor_researcher"]

    sponsor_techs = brief.get("sponsor_techs", [])
    prizes = brief.get("prizes", [])

    # Cross-reference sponsor_techs with prizes to build full picture
    sponsor_prizes = [p for p in prizes if p.get("sponsor")]

    sponsor_map = await complete_json(
        task="research-sponsor-apis",
        response_model=SponsorMap,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Research integration opportunities for this hackathon's sponsor prizes.

Hackathon: {brief.get('name')}
Theme: {brief.get('theme')}

Sponsor technologies available:
{json.dumps(sponsor_techs, indent=2)}

Prizes with sponsors:
{json.dumps(sponsor_prizes, indent=2)}

For each sponsor with a prize:
1. Describe the SIMPLEST integration that clearly qualifies
2. Give an HONEST time estimate (better to overestimate)
3. Calculate value_score = prize_amount / estimated_hours
4. Note any gotchas (approval delays, rate limits, credit cards required)
5. Describe how the integration is VISIBLE to judges in the UI

Sort opportunities by value_score (highest first).
Only recommend integrations that take ≤ 4 hours total.
Prioritize integrations that can run in parallel with the core product build.""",
        }],
        temperature=0.2,
    )

    await redis.set(f"hackathon:{hackathon_id}:sponsor_map", sponsor_map.model_dump_json(), ex=604800)
    logger.info(
        f"[forge:intel] Done. {len(sponsor_map.opportunities)} opportunities, "
        f"${sponsor_map.total_potential_prize:,.0f} total potential, "
        f"recommended: {sponsor_map.recommended_integrations}"
    )
    return sponsor_map


# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL RUNNER — all 4 intel agents together
# ─────────────────────────────────────────────────────────────────────────────

async def run_all_intelligence(hackathon_id: str, brief: dict) -> dict:
    """Run all 4 intelligence agents in parallel."""
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    logger.info(f"[intelligence] Running all 4 agents in parallel for: {brief.get('name')}")

    comp_report, judge_profile, sponsor_map = await asyncio.gather(
        analyze_competitors(hackathon_id, brief, redis),
        profile_judges(hackathon_id, brief, redis),
        research_sponsors(hackathon_id, brief, redis),
        return_exceptions=True,
    )

    # Handle partial failures gracefully
    results = {
        "comp_report": comp_report.model_dump() if not isinstance(comp_report, Exception) else {},
        "judge_profile": judge_profile.model_dump() if not isinstance(judge_profile, Exception) else {},
        "sponsor_map": sponsor_map.model_dump() if not isinstance(sponsor_map, Exception) else {},
    }

    for name, result in results.items():
        if not result:
            logger.warning(f"[intelligence] {name} failed — proceeding with defaults")

    # Signal strategy layer that intelligence is complete
    await redis.publish("agent:trigger", json.dumps({
        "hackathon_id": hackathon_id,
        "agent": "strategy_director",
        "input": {
            "brief": brief,
            "comp_report": results["comp_report"],
            "judge_profile": results["judge_profile"],
            "sponsor_map": results["sponsor_map"],
        },
    }))

    await redis.aclose()
    logger.info(f"[intelligence] All 4 agents complete. Strategy Director triggered.")
    return results
