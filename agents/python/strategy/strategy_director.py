"""
Strategy Director Agent
=======================
Synthesizes all Layer 1 intelligence into 3 ranked project concepts.
The most consequential strategy decision — everything downstream depends on this.

Consumes: HackathonBrief + CompReport + JudgeProfile + SponsorMap
Produces: ConceptBrief (3 ranked concepts for human selection)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from config.electronhub import complete_json
from config.agents_config import ALL_AGENTS

logger = logging.getLogger(__name__)
AGENT = ALL_AGENTS["strategy_director"]


# ── Data models ───────────────────────────────────────────────────────────────

class SponsorIntegrationPlan(BaseModel):
    sponsor: str
    api_name: str
    prize_amount: float
    integration_description: str
    estimated_hours: float
    ui_visibility: str        # how this integration is visible to judges
    eligibility_confidence: str  # "high" | "medium" | "low"


class ProjectConcept(BaseModel):
    rank: int                 # 1 = best, 3 = third best
    project_name: str
    tagline: str              # starts with a verb, under 12 words
    problem: str              # who has it, how much it hurts, specific numbers
    solution: str             # what it DOES (not IS), specific
    target_user: str          # specific persona, not "businesses"
    core_features: list[dict] # exactly 2 features with user_story + demo_moment
    why_it_wins: str          # specific reasoning referencing CompReport + JudgeProfile
    differentiation: str      # how it avoids being like past winners
    sponsor_integrations: list[SponsorIntegrationPlan]
    prize_eligibility: list[str]  # list of prize categories this can win
    demo_wow_moment: str      # the specific 10-second moment that creates the emotional response
    technical_risk: str       # honest assessment of what could go wrong
    win_probability_score: int  # 0-100
    feasibility_score: int    # 0-100
    sponsor_prize_score: int  # 0-100
    total_score: int


class ConceptBrief(BaseModel):
    concepts: list[ProjectConcept]  # exactly 3, ranked by total_score desc
    recommended_concept: int  # rank of the recommended concept (1-3)
    recommendation_rationale: str
    key_risks_overall: list[str]
    timeline_assessment: str  # honest: "This is achievable with 25% polish time reserved"


# ── Scoring logic ─────────────────────────────────────────────────────────────

async def score_concept(concept: ProjectConcept, sponsor_map: dict) -> ProjectConcept:
    """Verify and calibrate scores using explicit rubric."""
    # win_probability: alignment with judges + differentiation from past winners
    # feasibility: honest build time estimate vs available time
    # sponsor_prize: number of prizes × confidence × prize value

    total_prize_value = sum(
        si.prize_amount * (1.0 if si.eligibility_confidence == "high"
                           else 0.7 if si.eligibility_confidence == "medium"
                           else 0.4)
        for si in concept.sponsor_integrations
    )

    # Weighted score
    concept.total_score = int(
        concept.win_probability_score * 0.4 +
        concept.feasibility_score * 0.3 +
        concept.sponsor_prize_score * 0.3
    )

    return concept


# ── Main function ─────────────────────────────────────────────────────────────

async def generate_concepts(
    hackathon_brief: dict,
    comp_report: dict,
    judge_profile: dict,
    sponsor_map: dict,
) -> ConceptBrief:

    brief = await complete_json(
        task="generate-concepts",
        response_model=ConceptBrief,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Generate exactly 3 project concepts for this hackathon.
Each concept must be genuinely distinct — not just variations of the same idea.

=== HACKATHON BRIEF ===
{json.dumps(hackathon_brief, indent=2)}

=== COMPETITOR ANALYSIS (what WON and what FAILED) ===
{json.dumps(comp_report, indent=2)}

=== JUDGE PROFILE (what will resonate with THESE judges) ===
{json.dumps(judge_profile, indent=2)}

=== SPONSOR MAP (available prizes and integration complexity) ===
{json.dumps(sponsor_map, indent=2)}

HARD REQUIREMENTS FOR EACH CONCEPT:
1. Exactly 2 core features maximum (PM agent will enforce this — don't fight it)
2. Demo works without user login (demo mode with seeded data)
3. At least 2 sponsor integrations that are NATURAL to the product
4. Differentiated from the top past winners (see CompReport)
5. Buildable with 25% time reserved for polish

SCORING RUBRIC:
- win_probability (0-40): alignment with judges + differentiation + emotional resonance
- feasibility (0-30): honest build estimate, accounting for integration complexity
- sponsor_prize (0-30): total expected prize value × confidence × number of prizes

REQUIRED: Explain WHY each concept would win. Reference specific judges, 
specific past winner gaps, specific sponsor prize criteria.

rank=1 should be your best recommendation. Be honest about risks.""",
        }],
        temperature=0.4,
    )

    # Score calibration
    for concept in brief.concepts:
        await score_concept(concept, sponsor_map)

    # Sort by score and fix ranks
    brief.concepts.sort(key=lambda c: c.total_score, reverse=True)
    for i, concept in enumerate(brief.concepts):
        concept.rank = i + 1

    return brief


# ── Redis worker ──────────────────────────────────────────────────────────────

async def run_worker() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger")

    logger.info("[forge:strategy] Worker ready")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        if payload.get("agent") != "strategy_director":
            continue

        hackathon_id = payload["hackathon_id"]
        inp = payload["input"]

        await redis.set(f"task:{hackathon_id}:strategy_director", json.dumps({"status": "in-progress"}), ex=604800)

        try:
            brief = await generate_concepts(
                hackathon_brief=inp["brief"],
                comp_report=inp.get("comp_report", {}),
                judge_profile=inp.get("judge_profile", {}),
                sponsor_map=inp.get("sponsor_map", {}),
            )

            # Store for human checkpoint
            await redis.set(
                f"hackathon:{hackathon_id}:concepts",
                brief.model_dump_json(),
                ex=604800,
            )

            await redis.set(
                f"task:{hackathon_id}:strategy_director",
                json.dumps({"status": "done", "data": brief.model_dump()}),
                ex=604800,
            )

            # Notify human via Slack (Commander handles this)
            await redis.publish("commander:checkpoint", json.dumps({
                "hackathon_id": hackathon_id,
                "checkpoint": "concept_approval",
                "data": {
                    "concepts": [
                        {
                            "rank": c.rank,
                            "name": c.project_name,
                            "tagline": c.tagline,
                            "score": c.total_score,
                            "prizes": len(c.sponsor_integrations),
                            "why_it_wins": c.why_it_wins[:200],
                        }
                        for c in brief.concepts
                    ],
                    "recommended": brief.recommended_concept,
                },
            }))

            logger.info(
                f"[forge:strategy] Generated {len(brief.concepts)} concepts. "
                f"Recommended: rank {brief.recommended_concept} "
                f"({brief.concepts[brief.recommended_concept-1].project_name}, "
                f"score {brief.concepts[brief.recommended_concept-1].total_score})"
            )

        except Exception as e:
            logger.error(f"[forge:strategy] Failed: {e}", exc_info=True)
            await redis.set(
                f"task:{hackathon_id}:strategy_director",
                json.dumps({"status": "failed", "error": str(e)}),
                ex=604800,
            )

    await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(run_worker())
