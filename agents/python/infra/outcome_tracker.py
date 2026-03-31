# -*- coding: utf-8 -*-
"""
Outcome Tracker — Agent 30, Layer 7: Infrastructure
=====================================================
Closes the learning loop.

After judging day, this agent:
  1. Polls the hackathon page for results
  2. Scrapes placement, prize won, and any public judge feedback
  3. Calls MemoryKeeper.store_outcome() — the call that was never wired
  4. Stores what winning projects did differently (for next Competitor Analyst run)
  5. Updates Knowledge Updater with specific winning signals from THIS event

Without this agent, Forge submits and learns nothing.
With it, every run makes the next run better.

Triggered by:
  - Calendar Agent (scheduled 24-48h after submission_deadline)
  - Manual: python agents/python/infra/outcome_tracker.py --hackathon-id <id>
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from pydantic import BaseModel
from redis.asyncio import Redis

from config.electronhub import complete, complete_json
from config.agents_config import ALL_AGENTS

logger = logging.getLogger(__name__)
AGENT = ALL_AGENTS["outcome_tracker"]
BROWSER_URL = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")


# ── Data models ───────────────────────────────────────────────────────────────

class WinnerEntry(BaseModel):
    project_name: str
    team: str | None = None
    placement: str          # "1st", "2nd", "finalist", "honorable mention"
    prize_won: str | None = None
    prize_amount: float | None = None
    project_url: str | None = None
    tech_stack: list[str] = []
    what_stood_out: str     # inferred from description/demo if feedback not public


class HackathonResult(BaseModel):
    hackathon_id: str
    hackathon_name: str
    our_placement: str      # "1st" | "2nd" | "finalist" | "not_placed" | "unknown"
    our_prize_won: str | None = None
    our_prize_amount: float = 0.0
    winners: list[WinnerEntry]
    judge_feedback_public: str | None = None
    judged_at: str | None = None
    results_available: bool


class OutcomeAnalysis(BaseModel):
    what_worked: list[str]
    what_failed: list[str]
    design_decision_assessment: str
    sponsor_integration_assessment: str
    concept_strength_assessment: str
    learning_for_next_run: list[str]
    knowledge_update_signal: str    # one sentence to feed into LIVING_KNOWLEDGE


# ── Browser scraping ───────────────────────────────────────────────────────────

async def scrape_results(hackathon_url: str, platform: str) -> dict:
    """Ask browser layer to scrape the results/winners page."""
    results_urls = {
        "devpost": [
            f"{hackathon_url}/project/search?utf8=true&prizes[]=true",
            f"{hackathon_url}#winners",
            f"{hackathon_url}/prizes",
        ],
        "lablab":   [f"{hackathon_url}/results", f"{hackathon_url}#winners"],
        "devfolio": [f"{hackathon_url}/winners"],
        "mlh":      [f"{hackathon_url}/winners"],
    }
    urls_to_try = results_urls.get(platform, [f"{hackathon_url}/winners"])

    for url in urls_to_try:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BROWSER_URL}/scrape",
                    json={
                        "custom_urls": [url],
                        "extract_winners": True,
                        "limit_per_platform": 10,
                    },
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("winners") or data.get("hackathons"):
                            return data
        except Exception as e:
            logger.warning(f"[forge:outcome] Scrape failed for {url}: {e}")

    return {}


async def check_our_submission(
    hackathon_url: str,
    project_name: str,
    submission_url: str,
) -> dict:
    """Check our own submission page for any judge comments or placement."""
    if not submission_url or submission_url.startswith("file://"):
        return {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BROWSER_URL}/scrape",
                json={
                    "custom_urls": [submission_url],
                    "extract_feedback": True,
                    "limit_per_platform": 1,
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.warning(f"[forge:outcome] Submission scrape failed: {e}")

    return {}


# ── Result parsing ────────────────────────────────────────────────────────────

async def parse_results(
    scraped_data: dict,
    project_name: str,
    brief: dict,
    ux_audit_score: float,
    submission_url: str,
) -> HackathonResult:

    hackathon_name = brief.get("name", "Unknown")
    scraped_text = json.dumps(scraped_data, indent=2)[:3000]

    class ParsedResult(BaseModel):
        our_placement: str
        our_prize_won: str | None = None
        our_prize_amount: float = 0.0
        winners: list[dict]
        judge_feedback: str | None = None
        judged_at: str | None = None
        results_available: bool

    parsed = await complete_json(
        task="analyze-competitors",
        response_model=ParsedResult,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Parse these hackathon results.

Our project name: {project_name}
Hackathon: {hackathon_name}
Submission URL: {submission_url}

Scraped data:
{scraped_text}

Determine:
1. our_placement: "1st" | "2nd" | "3rd" | "finalist" | "honorable_mention" | "not_placed" | "unknown"
2. our_prize_won: prize name if we won one, null if not
3. our_prize_amount: dollar amount if won, 0.0 if not
4. winners: list of {{project_name, placement, prize_won, prize_amount, tech_stack, what_stood_out}}
   for top placements found in the results
5. judge_feedback: any public judge comments about our project specifically
6. judged_at: when judging happened if visible
7. results_available: true if results were findable, false if page had no results yet

If the results page has no winners yet, set results_available=false.""",
        }],
        temperature=0.1,
    )

    winners = [WinnerEntry(
        project_name=w.get("project_name", "Unknown"),
        team=w.get("team"),
        placement=w.get("placement", "unknown"),
        prize_won=w.get("prize_won"),
        prize_amount=w.get("prize_amount"),
        project_url=w.get("project_url"),
        tech_stack=w.get("tech_stack", []),
        what_stood_out=w.get("what_stood_out", ""),
    ) for w in parsed.winners[:5]]

    return HackathonResult(
        hackathon_id=brief.get("hackathon_id", ""),
        hackathon_name=hackathon_name,
        our_placement=parsed.our_placement,
        our_prize_won=parsed.our_prize_won,
        our_prize_amount=parsed.our_prize_amount,
        winners=winners,
        judge_feedback_public=parsed.judge_feedback,
        judged_at=parsed.judged_at,
        results_available=parsed.results_available,
    )


# ── Outcome analysis ──────────────────────────────────────────────────────────

async def analyze_outcome(
    result: HackathonResult,
    project_plan: dict,
    design_spec: dict,
    ux_audit_score: float,
    sponsor_integrations: list[str],
) -> OutcomeAnalysis:

    winners_summary = "\n".join([
        f"- {w.placement}: {w.project_name} — {w.what_stood_out}"
        for w in result.winners
    ]) or "No winner data available"

    analysis = await complete_json(
        task="analyze-competitors",
        response_model=OutcomeAnalysis,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Analyze this hackathon outcome to extract learning.

OUR RESULT:
- Placement: {result.our_placement}
- Prize: {result.our_prize_won or 'none'} (${result.our_prize_amount:,.0f})
- Project: {project_plan.get('project_name')}
- Concept: {project_plan.get('tagline')}
- Design personality used: {design_spec.get('personality', 'unknown')}
- UX Audit score: {ux_audit_score}/10
- Sponsor integrations built: {', '.join(sponsor_integrations) or 'none'}

WINNERS (what beat us or won alongside us):
{winners_summary}

Judge feedback (public): {result.judge_feedback_public or 'none available'}

Produce honest analysis:
1. what_worked: specific things that likely helped (max 5 items)
2. what_failed: specific things that likely hurt (max 5 items)
3. design_decision_assessment: was the design personality choice right?
4. sponsor_integration_assessment: did sponsor integrations help our score?
5. concept_strength_assessment: how did our concept hold up vs winners?
6. learning_for_next_run: actionable changes for next hackathon (max 5)
7. knowledge_update_signal: one sentence for LIVING_KNOWLEDGE (e.g., "Enterprise workflow agents with ERP integration won $20k at this event over generic chatbots")

Be direct. If we lost, say why. Don't sugarcoat.""",
        }],
        temperature=0.3,
    )
    return analysis


# ── Memory loop closure ───────────────────────────────────────────────────────

async def store_outcome_and_close_loop(
    hackathon_id: str,
    result: HackathonResult,
    analysis: OutcomeAnalysis,
    ux_audit_score: float,
    project_plan: dict,
) -> None:
    """Actually call store_outcome() — the call that was missing before."""
    from agents.python.infra.memory_keeper import get_memory_keeper

    memory = get_memory_keeper()
    await memory.store_outcome(
        hackathon_id=hackathon_id,
        hackathon_name=result.hackathon_name,
        outcome={
            "result": result.our_placement,
            "prize_won": result.our_prize_won,
            "prize_amount": result.our_prize_amount,
            "concept": project_plan.get("tagline", ""),
            "project_name": project_plan.get("project_name", ""),
            "what_worked": analysis.what_worked,
            "what_failed": analysis.what_failed,
            "ux_audit_score": ux_audit_score,
            "design_decision": analysis.design_decision_assessment,
            "sponsor_assessment": analysis.sponsor_integration_assessment,
        },
    )
    logger.info(f"[forge:outcome] Memory loop closed for {result.hackathon_name}")

    # Also store the winning projects we observed for Competitor Analyst's next run
    for winner in result.winners[:3]:
        await memory.store_code_artifact(
            hackathon_id=hackathon_id,
            artifact_type="past-winner",
            name=f"{result.hackathon_name} — {winner.placement}: {winner.project_name}",
            code="",  # no code, just metadata
            description=(
                f"Won {winner.prize_won or 'placement'} at {result.hackathon_name}. "
                f"Tech: {', '.join(winner.tech_stack)}. "
                f"What stood out: {winner.what_stood_out}"
            ),
        )

    # Feed learning signal into LIVING_KNOWLEDGE via Knowledge Updater mechanism
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis.rpush("forge:outcome_signals", json.dumps({
        "hackathon": result.hackathon_name,
        "signal": analysis.knowledge_update_signal,
        "placement": result.our_placement,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))
    await redis.expire("forge:outcome_signals", 86400 * 90)  # keep 90 days
    await redis.aclose()

    logger.info(f"[forge:outcome] Signal stored: {analysis.knowledge_update_signal}")


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def run_outcome_tracker(
    hackathon_id: str,
    retry_if_no_results: bool = True,
) -> HackathonResult | None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    # Load all context from Redis
    brief_raw    = await redis.get(f"hackathon:{hackathon_id}:brief")
    plan_raw     = await redis.get(f"hackathon:{hackathon_id}:project_plan")
    design_raw   = await redis.get(f"hackathon:{hackathon_id}:design_spec")
    audit_raw    = await redis.get(f"task:{hackathon_id}:ux_auditor")
    sub_raw      = await redis.get(f"task:{hackathon_id}:submission")
    sponsor_raw  = await redis.get(f"hackathon:{hackathon_id}:sponsor_integration_manifest")

    await redis.aclose()

    if not brief_raw:
        logger.error(f"[forge:outcome] No brief found for {hackathon_id}")
        return None

    brief       = json.loads(brief_raw)
    project_plan = json.loads(plan_raw) if plan_raw else {}
    design_spec  = json.loads(design_raw) if design_raw else {}
    sub_data     = json.loads(sub_raw).get("data", {}) if sub_raw else {}
    submission_url = sub_data.get("submission_url", "")
    ux_audit_score = (json.loads(audit_raw).get("data", {}).get("overall_score", 0.0)
                      if audit_raw else 0.0)
    sponsor_manifest = json.loads(sponsor_raw) if sponsor_raw else {}
    sponsor_integrations = sponsor_manifest.get("recommended_integrations", [])

    platform   = brief.get("platform", "devpost")
    project_name = project_plan.get("project_name", "Our Project")

    logger.info(f"[forge:outcome] Checking results for: {brief.get('name')}")

    # 1. Scrape results
    scraped = await scrape_results(brief["url"], platform)

    # 2. Also check our own submission page for feedback
    if submission_url:
        our_sub = await check_our_submission(brief["url"], project_name, submission_url)
        scraped.update(our_sub)

    # 3. Parse what we found
    result = await parse_results(scraped, project_name, brief, ux_audit_score, submission_url)

    if not result.results_available and retry_if_no_results:
        logger.info(f"[forge:outcome] Results not posted yet — will retry in 6 hours")
        # Schedule retry via Redis with TTL
        redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        await redis.set(
            f"outcome:retry:{hackathon_id}",
            json.dumps({"retry_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()}),
            ex=86400,
        )
        await redis.aclose()
        return None

    # 4. Analyze outcome
    analysis = await analyze_outcome(
        result, project_plan, design_spec, ux_audit_score, sponsor_integrations
    )

    # 5. Close the memory loop — store everything
    await store_outcome_and_close_loop(
        hackathon_id, result, analysis, ux_audit_score, project_plan
    )

    # 6. Save full outcome report to disk
    output_dir = Path(f"/tmp/hackathon-{hackathon_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "result": result.model_dump(),
        "analysis": analysis.model_dump(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "outcome-report.json").write_text(json.dumps(report, indent=2))

    logger.info(
        f"[forge:outcome] DONE — {brief.get('name')}: {result.our_placement} "
        f"(${result.our_prize_amount:,.0f}). "
        f"Worked: {analysis.what_worked[:2]}. "
        f"Failed: {analysis.what_failed[:2]}"
    )
    return result


# ── Redis worker ──────────────────────────────────────────────────────────────

async def run_worker() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger", "forge:check_outcomes")
    logger.info("[forge:outcome] Outcome Tracker worker ready")

    async def check_pending_retries():
        """Check for hackathons waiting for results to post."""
        while True:
            await asyncio.sleep(3600)  # check every hour
            try:
                redis2 = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
                retry_keys = await redis2.keys("outcome:retry:*")
                now = datetime.now(timezone.utc)
                for key in retry_keys:
                    raw = await redis2.get(key)
                    if not raw:
                        continue
                    data = json.loads(raw)
                    retry_at = datetime.fromisoformat(data["retry_at"])
                    if now >= retry_at:
                        hackathon_id = key.split(":")[-1]
                        await redis2.delete(key)
                        logger.info(f"[forge:outcome] Retrying outcome check for {hackathon_id}")
                        asyncio.create_task(run_outcome_tracker(hackathon_id, retry_if_no_results=True))
                await redis2.aclose()
            except Exception as e:
                logger.error(f"[forge:outcome] Retry check failed: {e}")

    asyncio.create_task(check_pending_retries())

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])

        # Triggered by agent:trigger channel
        if payload.get("agent") == "outcome_tracker":
            hackathon_id = payload["hackathon_id"]
            await redis.set(
                f"task:{hackathon_id}:outcome_tracker",
                json.dumps({"status": "in-progress"}),
                ex=604800,
            )
            try:
                result = await run_outcome_tracker(hackathon_id)
                await redis.set(
                    f"task:{hackathon_id}:outcome_tracker",
                    json.dumps({
                        "status": "done",
                        "data": result.model_dump() if result else {"pending": True},
                    }),
                    ex=604800,
                )
            except Exception as e:
                logger.error(f"[forge:outcome] Failed for {hackathon_id}: {e}", exc_info=True)
                await redis.set(
                    f"task:{hackathon_id}:outcome_tracker",
                    json.dumps({"status": "failed", "error": str(e)}),
                    ex=604800,
                )

        # Triggered by calendar — check all recent submissions
        elif message["channel"] == "forge:check_outcomes":
            ids_raw = payload.get("hackathon_ids", [])
            for hid in ids_raw:
                asyncio.create_task(run_outcome_tracker(hid, retry_if_no_results=True))

    await redis.aclose()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Forge Outcome Tracker")
    parser.add_argument("--hackathon-id", required=True)
    parser.add_argument("--no-retry", action="store_true")
    args = parser.parse_args()

    async def main():
        result = await run_outcome_tracker(
            args.hackathon_id,
            retry_if_no_results=not args.no_retry,
        )
        if result:
            print(f"\nResult: {result.our_placement}")
            print(f"Prize:  {result.our_prize_won or 'none'} (${result.our_prize_amount:,.0f})")
            print(f"Winners found: {len(result.winners)}")

    asyncio.run(main())
