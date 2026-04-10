# -*- coding: utf-8 -*-
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

from pydantic import BaseModel

from config.electronhub import reflect_and_refine
from config.agents_config import ALL_AGENTS
from config.forge_trace import trace_op, register_artifact, set_agent_context
from config.redis_client import get_redis

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
    # Guard: if the LLM scored on the old 0-40/0-30 scale, rescale to 0-100
    if concept.win_probability_score <= 40 and concept.feasibility_score <= 30:
        concept.win_probability_score = min(100, int(concept.win_probability_score * 2.5))
        concept.feasibility_score = min(100, int(concept.feasibility_score * 3.33))
        concept.sponsor_prize_score = min(100, int(concept.sponsor_prize_score * 3.33))

    # Boost sponsor_prize_score when real prize money backs the integrations
    weighted_prize_value = sum(
        si.prize_amount * (1.0 if si.eligibility_confidence == "high"
                           else 0.7 if si.eligibility_confidence == "medium"
                           else 0.4)
        for si in concept.sponsor_integrations
    )
    if weighted_prize_value > 0 and concept.sponsor_prize_score < 80:
        prize_bonus = min(15, int(weighted_prize_value / 1000))
        concept.sponsor_prize_score = min(100, concept.sponsor_prize_score + prize_bonus)

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
    hackathon_id: str = "",
) -> ConceptBrief:
    import time as _t
    t0 = _t.monotonic()
    set_agent_context(hackathon_id, "strategy_director")
    logger.info(f"[forge:strategy] generate_concepts() START (hackathon={hackathon_id})")

    # ── Feature 1: Query memory for what worked in past similar hackathons ────
    past_learnings = ""
    memdir_notes = ""
    try:
        from agents.python.infra.memory_keeper import get_memory_keeper
        from config.run_context import build_memdir_context_for_agent

        logger.info("[forge:strategy] Querying memory for past learnings...")
        memory = get_memory_keeper()
        theme = hackathon_brief.get("theme", hackathon_brief.get("name", "hackathon"))
        past_results = await memory.get_relevant_past(theme, limit=4)
        logger.info(f"[forge:strategy] Memory returned {len(past_results)} results ({_t.monotonic()-t0:.1f}s)")

        if past_results:
            past_lines = []
            for r in past_results:
                mem = r.get("memory", r.get("text", str(r)))
                past_lines.append(f"  - {mem}")
            past_learnings = "\n=== MEMORY FROM PAST RUNS (what worked and failed) ===\n" + "\n".join(past_lines) + "\n"

        memdir_notes = await build_memdir_context_for_agent("strategy_director")
        logger.info(f"[forge:strategy] Memory + memdir loaded ({_t.monotonic()-t0:.1f}s)")
    except Exception as e:
        logger.warning(f"[forge:strategy] Memory query failed (continuing without it): {e}")

    prompt_size = (
        len(json.dumps(hackathon_brief))
        + len(json.dumps(comp_report))
        + len(json.dumps(judge_profile))
        + len(json.dumps(sponsor_map))
        + len(past_learnings)
    )
    logger.info(
        f"[forge:strategy] Calling reflect_and_refine(generate-concepts) "
        f"| prompt_size≈{prompt_size} chars ({_t.monotonic()-t0:.1f}s)"
    )

    concept_messages = [{
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
{past_learnings}
HARD REQUIREMENTS FOR EACH CONCEPT:
1. Exactly 2 core features maximum (PM agent will enforce this — don't fight it)
2. Demo works without user login (demo mode with seeded data)
3. At least 2 sponsor integrations that are NATURAL to the product
4. Differentiated from the top past winners (see CompReport)
5. Buildable with 25% time reserved for polish

SCORING RUBRIC (each dimension 0-100, total = weighted average):
- win_probability_score (0-100): alignment with judges + differentiation + emotional resonance
- feasibility_score (0-100): honest build estimate, accounting for integration complexity
- sponsor_prize_score (0-100): number of eligible prizes × confidence × prize value potential
Total = 0.4 × win_probability_score + 0.3 × feasibility_score + 0.3 × sponsor_prize_score
A strong concept should score 60-85 total. Over 85 means you are not being honest about risks.

REQUIRED: Explain WHY each concept would win. Reference specific judges, 
specific past winner gaps, specific sponsor prize criteria.

rank=1 should be your best recommendation. Be honest about risks.""",
    }]

    concept_critique_prompt = """Evaluate these 3 hackathon project concepts against these criteria:

1. DISTINCTIVENESS: Are the 3 concepts genuinely different approaches, not variations of the same idea?
2. SPONSOR ALIGNMENT: Are sponsor integrations natural to the product (not bolted on)?
3. FEASIBILITY HONESTY: Are build estimates realistic given integration complexity? Is 25% polish time preserved?
4. DEMO PATH CLARITY: Does each concept have a clear, compelling demo_wow_moment?
5. WIN PROBABILITY: Does the reasoning reference specific judges and past winner gaps?
6. SCORING: Are scores in the 0-100 range per dimension, with totals between 60-85 for strong concepts?

Flag any concept that is vague, has unrealistic sponsor integrations, or lacks specific judge/winner references."""

    async with trace_op("llm", "strategy:generate_concepts") as span:
        span.input = {"hackathon": hackathon_brief.get("name"), "prompt_size": prompt_size}
        brief = await reflect_and_refine(
            task="generate-concepts",
            response_model=ConceptBrief,
            system_prompt=AGENT.system_prompt + memdir_notes,
            messages=concept_messages,
            temperature=0.4,
            critique_prompt=concept_critique_prompt,
            quality_threshold=7.0,
            max_iterations=3,
            critique_task="critique-concepts",
        )
        span.output = {"concepts": len(brief.concepts), "top_score": brief.concepts[0].total_score if brief.concepts else 0}
    logger.info(
        f"[forge:strategy] reflect_and_refine returned {len(brief.concepts)} concepts "
        f"({_t.monotonic()-t0:.1f}s)"
    )

    for concept in brief.concepts:
        await score_concept(concept, sponsor_map)

    brief.concepts.sort(key=lambda c: c.total_score, reverse=True)
    for i, concept in enumerate(brief.concepts):
        concept.rank = i + 1

    await register_artifact(hackathon_id, "strategy_director", "concepts", "json", f"{len(brief.concepts)} ranked concepts, top: {brief.concepts[0].project_name}")

    logger.info(
        f"[forge:strategy] generate_concepts() DONE in {_t.monotonic()-t0:.1f}s | "
        f"top concept: {brief.concepts[0].project_name} (score={brief.concepts[0].total_score})"
    )
    return brief


# ── Redis worker ──────────────────────────────────────────────────────────────

async def run_worker() -> None:
    redis = get_redis()
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
        set_agent_context(hackathon_id, "strategy_director")
        inp = payload["input"]

        await redis.set(f"task:{hackathon_id}:strategy_director", json.dumps({"status": "in-progress"}), ex=604800)

        try:
            brief = await generate_concepts(
                hackathon_brief=inp["brief"],
                comp_report=inp.get("comp_report", {}),
                judge_profile=inp.get("judge_profile", {}),
                sponsor_map=inp.get("sponsor_map", {}),
                hackathon_id=hackathon_id,
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

            # Notify human via Discord (Commander handles this)
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
