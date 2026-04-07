# -*- coding: utf-8 -*-
"""
UX Auditor Agent
================
The anti-slop guardian. Has veto power over all UI work.
Browses the actual live Vercel preview URL and scores it against
the design critique rubric.

This is the ONLY agent with blocking veto power.
If this agent rejects the design, frontend + polish agents must iterate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import aiohttp
from pydantic import BaseModel

from config.electronhub import complete_json
from config.redis_client import get_redis
from config.agents_config import ALL_AGENTS
from config.design_constitution import DESIGN_CRITIQUE_RUBRIC, ANTI_SLOP_RULES
from config.forge_trace import trace_op, register_artifact, set_agent_context

logger = logging.getLogger(__name__)
AGENT = ALL_AGENTS["ux_auditor"]
UX_MIN_SCORE = float(os.environ.get("UX_AUDIT_MIN_SCORE", "7.0"))

BROWSER_URL = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")


# ── Audit models ──────────────────────────────────────────────────────────────

class CriterionScore(BaseModel):
    score: int                  # 1-10
    observations: list[str]     # specific, actionable notes


class AntiSlopViolation(BaseModel):
    rule_number: int            # which rule from ANTI_SLOP_RULES
    violation: str              # what specifically was violated
    file_path: str | None       # if known
    fix_instruction: str        # exactly how to fix it


class UXAuditReport(BaseModel):
    preview_url: str
    first_impression: CriterionScore
    visual_polish: CriterionScore
    interaction_quality: CriterionScore
    content_realism: CriterionScore
    demo_path_clarity: CriterionScore
    brand_coherence: CriterionScore
    overall_score: float
    anti_slop_violations: list[AntiSlopViolation]
    blockers: list[str]         # must fix before quality review approval
    warnings: list[str]         # should fix in polish phase
    approved: bool              # True only if overall >= 7.0 AND no blockers
    iteration_instructions: str  # specific instructions for next iteration


# ── Browser screenshot capture ────────────────────────────────────────────────

async def capture_screenshots(preview_url: str, screens: list[str]) -> list[dict]:
    """Ask browser layer to screenshot each screen in the demo path."""
    set_agent_context("", "ux_auditor")
    screenshots = []

    async with trace_op("http", "audit:capture_screenshots") as span:
        async with aiohttp.ClientSession() as session:
            for route in screens:
                url = f"{preview_url}{route}"
                try:
                    async with session.post(
                        f"{BROWSER_URL}/screenshot",
                        json={
                            "url": url,
                            "viewports": [
                                {"width": 375, "height": 812, "label": "mobile"},
                                {"width": 1440, "height": 900, "label": "desktop"},
                            ],
                            "wait_for_selector": "body",
                            "wait_ms": 2000,
                        },
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        data = await resp.json()
                        screenshots.append({
                            "route": route,
                            "url": url,
                            "mobile_path": data.get("mobile_path"),
                            "desktop_path": data.get("desktop_path"),
                            "console_errors": data.get("console_errors", []),
                            "has_layout_shift": data.get("has_layout_shift", False),
                        })
                except Exception as e:
                    logger.warning(f"[forge:audit] Screenshot failed for {url}: {e}")
                    screenshots.append({"route": route, "url": url, "error": str(e)})
        span.output = {"screenshot_count": len(screenshots)}

    return screenshots


async def run_lighthouse(preview_url: str) -> dict:
    """Run Lighthouse audit via browser layer."""
    try:
        async with trace_op("http", "audit:lighthouse") as span:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BROWSER_URL}/lighthouse",
                    json={"url": preview_url},
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    return await resp.json()
    except Exception as e:
        return {"error": str(e), "performance": 0, "accessibility": 0}


# ── Core audit ────────────────────────────────────────────────────────────────

async def audit_design(
    preview_url: str,
    design_spec: dict,
    design_md_content: str,
    screenshots: list[dict],
    lighthouse: dict,
) -> UXAuditReport:

    # Build audit context
    console_errors_summary = []
    for ss in screenshots:
        if ss.get("console_errors"):
            console_errors_summary.extend([
                f"{ss['route']}: {err}" for err in ss["console_errors"]
            ])

    audit_context = f"""
PREVIEW URL: {preview_url}

SCREENSHOTS CAPTURED:
{json.dumps([{"route": ss["route"], "errors": ss.get("console_errors", []), "layout_shift": ss.get("has_layout_shift")} for ss in screenshots], indent=2)}

LIGHTHOUSE SCORES:
- Performance: {lighthouse.get("performance", "unknown")}
- Accessibility: {lighthouse.get("accessibility", "unknown")}
- Best Practices: {lighthouse.get("best_practices", "unknown")}
- SEO: {lighthouse.get("seo", "unknown")}

CONSOLE ERRORS FOUND:
{chr(10).join(console_errors_summary) or "None"}

DESIGN SPEC:
Personality: {design_spec.get("personality")}
Screens: {[s.get("name") for s in design_spec.get("screens", [])]}
Demo entry: {design_spec.get("demo_entry_route")}
Anti-slop self-check claimed: {design_spec.get("anti_slop_self_check", [])}

DESIGN.md summary:
{design_md_content[:2000]}
"""

    async with trace_op("llm", "audit:score_design") as span:
        report = await complete_json(
            task="audit-ux-flow",
            response_model=UXAuditReport,
            system_prompt=AGENT.system_prompt,
            messages=[{
                "role": "user",
                "content": f"""{DESIGN_CRITIQUE_RUBRIC}

{ANTI_SLOP_RULES}

AUDIT THIS DESIGN:
{audit_context}

SCORING NOTES:
- Score each dimension 1-10 with specific observations
- For anti_slop_violations: list ONLY actual violations found (not potential ones)
- For blockers: only issues that would fail the "first 30 seconds" test
- approved=true ONLY if overall_score >= {UX_MIN_SCORE} AND anti_slop_violations is empty AND blockers is empty
- If not approved: iteration_instructions must be SPECIFIC (file paths, element names, exact fixes)

VETO CRITERIA (auto-blocked):
- Any anti-slop violation from the list
- Console errors on the demo path
- Lighthouse Accessibility < 85
- Empty states visible on demo path screens
- Mobile layout broken at 375px (check horizontal scroll)
- Primary action not visible above fold on desktop""",
            }],
            temperature=0.2,
        )
        span.output = {"score": report.overall_score, "approved": report.approved}

    # Override approval if lighthouse scores are too low
    if lighthouse.get("accessibility", 100) < 85:
        report.approved = False
        report.blockers.append(
            f"Lighthouse Accessibility score {lighthouse.get('accessibility')} < 85. "
            "Fix ARIA labels, color contrast, and keyboard navigation."
        )

    if lighthouse.get("performance", 100) < 70:
        report.warnings.append(
            f"Lighthouse Performance score {lighthouse.get('performance')} < 70. "
            "Add code splitting, optimize images, check bundle size."
        )

    report.overall_score = (
        report.first_impression.score * 1.5 +
        report.visual_polish.score * 1.5 +
        report.interaction_quality.score * 1.0 +
        report.content_realism.score * 1.5 +
        report.demo_path_clarity.score * 2.0 +
        report.brand_coherence.score * 1.0
    ) / 8.5  # weighted average

    report.approved = (
        report.overall_score >= UX_MIN_SCORE
        and len(report.anti_slop_violations) == 0
        and len(report.blockers) == 0
    )

    return report


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def run_ux_audit(
    hackathon_id: str,
    preview_url: str,
    design_spec: dict,
    design_md_path: str,
) -> UXAuditReport:
    set_agent_context(hackathon_id, "ux_auditor")

    logger.info(f"[forge:audit] Starting audit: {preview_url}")

    # Load DESIGN.md
    try:
        with open(design_md_path, encoding="utf-8") as f:
            design_md_content = f.read()
    except FileNotFoundError:
        design_md_content = "DESIGN.md not found"

    # Get demo path screens to audit
    screens = [s.get("route") for s in design_spec.get("screens", [])
               if s.get("demo_path_position") is not None]
    if not screens:
        screens = ["/"]

    # Run parallel: screenshots + lighthouse
    screenshots, lighthouse = await asyncio.gather(
        capture_screenshots(preview_url, screens),
        run_lighthouse(preview_url),
    )

    # Score the design
    report = await audit_design(
        preview_url=preview_url,
        design_spec=design_spec,
        design_md_content=design_md_content,
        screenshots=screenshots,
        lighthouse=lighthouse,
    )

    logger.info(
        f"[forge:audit] Audit complete: score={report.overall_score:.1f}/10, "
        f"approved={report.approved}, "
        f"violations={len(report.anti_slop_violations)}, "
        f"blockers={len(report.blockers)}"
    )

    if not report.approved:
        logger.warning(f"[forge:audit] BLOCKED. Blockers: {report.blockers}")
        logger.warning(f"[forge:audit] Instructions: {report.iteration_instructions}")

    return report


# ── Redis worker ──────────────────────────────────────────────────────────────

async def run_worker() -> None:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger")

    logger.info("[forge:audit] Worker ready — the anti-slop guardian is watching")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        if payload.get("agent") != "ux_auditor":
            continue

        hackathon_id = payload["hackathon_id"]
        inp = payload["input"]

        set_agent_context(hackathon_id, "ux_auditor")

        await redis.set(f"task:{hackathon_id}:ux_auditor", json.dumps({"status": "in-progress"}), ex=604800)

        try:
            report = await run_ux_audit(
                hackathon_id=hackathon_id,
                preview_url=inp["preview_url"],
                design_spec=inp.get("design_spec", {}),
                design_md_path=inp.get("design_md_path", ""),
            )

            await redis.set(
                f"task:{hackathon_id}:ux_auditor",
                json.dumps({"status": "done", "data": report.model_dump()}),
                ex=604800,
            )

            # If blocked, notify commander to route back to frontend/polish agents
            if not report.approved:
                await redis.publish("commander:audit_failed", json.dumps({
                    "hackathon_id": hackathon_id,
                    "score": report.overall_score,
                    "blockers": report.blockers,
                    "instructions": report.iteration_instructions,
                }))

        except Exception as e:
            logger.error(f"[forge:audit] Failed: {e}", exc_info=True)
            await redis.set(
                f"task:{hackathon_id}:ux_auditor",
                json.dumps({"status": "failed", "error": str(e)}),
                ex=604800,
            )

    await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(run_worker())
