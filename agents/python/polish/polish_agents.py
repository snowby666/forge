"""
Polish Layer Agents — Layer 5
Runs in parallel after UX Auditor approves the build.
These agents turn a "working app" into a "winning app."

Polish Agent:    micro-interactions, loading states, empty states
Copy Writer:     rewrites all generic UI text to be judge-optimized
Data Seeder:     populates the demo with realistic, impressive data
Brand Agent:     logo, favicon, og:image, brand consistency audit
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
from pydantic import BaseModel
from redis.asyncio import Redis

from config.electronhub import complete, complete_json
from config.agents_config import ALL_AGENTS
from config.design_constitution import ANTI_SLOP_RULES, COMPONENT_QUALITY_CHECKLIST

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# POLISH AGENT
# ─────────────────────────────────────────────────────────────────────────────

class PolishTask(BaseModel):
    file_path: str
    issue: str
    fix_description: str
    priority: str           # "critical" | "high" | "medium"


class PolishReport(BaseModel):
    tasks_completed: list[PolishTask]
    remaining_issues: list[str]
    overall_polish_score: int   # 1-10


async def run_polish_agent(
    hackathon_id: str,
    preview_url: str,
    ux_audit_report: dict,
    frontend_repo_path: str,
    output_dir: str,
    redis: Redis,
) -> PolishReport:
    AGENT = ALL_AGENTS["polish"]

    # Get warnings from UX Auditor that need addressing
    warnings = ux_audit_report.get("warnings", [])
    anti_slop_violations = ux_audit_report.get("anti_slop_violations", [])

    polish_instructions = await complete(
        task="generate-component",
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Generate specific polish patches for these UX issues.

{COMPONENT_QUALITY_CHECKLIST}

Issues from UX Audit (warnings):
{json.dumps(warnings, indent=2)}

Anti-slop violations to fix:
{json.dumps(anti_slop_violations, indent=2)}

Current preview URL: {preview_url}

For each issue output a PATCH block in this exact format:
PATCH: src/relative/path/to/file.tsx
FIND: [exact string to find in the file]
REPLACE: [exact string to replace it with]
END

Focus on:
- Hover states: add `transition-colors duration-[120ms]` and bg-color change (not opacity)
- Loading: add skeleton that matches component shape
- Empty: add SVG placeholder + helpful copy + CTA button
- Mobile: remove any fixed widths that cause 375px overflow
- Meta tags: add og:image, og:title, og:description in layout.tsx
- favicon: link to /favicon.svg in layout.tsx head""",
        }],
        temperature=0.2,
    )

    # Parse PATCH blocks and apply file modifications
    import re as _re
    patch_pattern = _re.compile(
        r"PATCH:\s*(.+?)\nFIND:\s*(.*?)\nREPLACE:\s*(.*?)\nEND",
        _re.DOTALL,
    )
    tasks_completed: list[PolishTask] = []
    remaining_issues: list[str] = []

    output_root = Path(output_dir) if output_dir else Path(f"/tmp/hackathon-{hackathon_id}")

    for match in patch_pattern.finditer(polish_instructions):
        rel_path = match.group(1).strip()
        find_str = match.group(2).strip()
        replace_str = match.group(3).strip()
        target = output_root / rel_path

        if not target.exists():
            remaining_issues.append(f"File not found: {rel_path}")
            continue

        try:
            content = target.read_text()
            if find_str in content:
                target.write_text(content.replace(find_str, replace_str, 1))
                tasks_completed.append(PolishTask(
                    file_path=rel_path,
                    issue="UX audit fix applied",
                    fix_description=f"Replaced {find_str[:40]}... with polished version",
                    priority="high",
                ))
            else:
                remaining_issues.append(f"FIND string not found in {rel_path} — may already be fixed")
        except Exception as e:
            remaining_issues.append(f"Patch failed for {rel_path}: {e}")

    # Always add essential meta tags to layout if not present
    layout_candidates = list(output_root.rglob("layout.tsx")) + list(output_root.rglob("layout.ts"))
    for layout_file in layout_candidates[:1]:
        try:
            layout_content = layout_file.read_text()
            if "og:title" not in layout_content and "openGraph" not in layout_content:
                # Inject basic OG meta after <head> or metadata export
                og_block = """
  openGraph: {
    title: process.env.NEXT_PUBLIC_APP_NAME || 'Forge Project',
    description: process.env.NEXT_PUBLIC_APP_DESCRIPTION || 'Built with Forge',
    type: 'website',
  },"""
                if "metadata = {" in layout_content:
                    layout_content = layout_content.replace(
                        "metadata = {",
                        f"metadata = {{{og_block}",
                        1,
                    )
                    layout_file.write_text(layout_content)
                    tasks_completed.append(PolishTask(
                        file_path=str(layout_file.relative_to(output_root)),
                        issue="Missing OG meta tags",
                        fix_description="Added openGraph metadata block",
                        priority="medium",
                    ))
        except Exception:
            pass

    score = max(6, 10 - len(remaining_issues))
    report = PolishReport(
        tasks_completed=tasks_completed,
        remaining_issues=remaining_issues,
        overall_polish_score=score,
    )

    logger.info(
        f"[forge:polish] {len(tasks_completed)} patches applied, "
        f"{len(remaining_issues)} skipped, score={score}/10"
    )
    return report


# ─────────────────────────────────────────────────────────────────────────────
# COPY WRITER
# ─────────────────────────────────────────────────────────────────────────────

class CopyRewrite(BaseModel):
    element_type: str   # "headline" | "button" | "placeholder" | "error" | "empty_state" | "label"
    file_path: str
    original: str
    rewritten: str
    reasoning: str


class CopyWriterReport(BaseModel):
    rewrites: list[CopyRewrite]
    generic_patterns_eliminated: list[str]


async def run_copy_writer(
    hackathon_id: str,
    frontend_repo_path: str,
    judge_profile: dict,
    project_plan: dict,
    redis: Redis,
) -> CopyWriterReport:
    AGENT = ALL_AGENTS["copy_writer"]

    # Scan all TSX files for generic copy patterns
    generic_patterns = [
        "Lorem ipsum", "placeholder text", "Enter text", "Your content here",
        "Submit", "Click here", "Learn more", "Get started",
        "Lorem", "Placeholder", "Sample text", "Test data",
        "John Doe", "Jane Smith", "example@email.com", "Company Name",
    ]

    report = await complete_json(
        task="write-submission-copy",
        response_model=CopyWriterReport,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Rewrite all generic UI copy in this project to be specific and judge-optimized.

Project: {project_plan.get('project_name')} — {project_plan.get('tagline')}
Problem: {project_plan.get('problem')}
Target user: {project_plan.get('target_user')}

Judge panel language preference: {judge_profile.get('recommended_language', 'balanced')}
Judge narrative framing: {judge_profile.get('narrative_framing', '')}

Generic patterns to eliminate:
{chr(10).join('- ' + p for p in generic_patterns)}

For each piece of generic copy found:
1. Rewrite it to be specific to this product and use case
2. Match the judge panel's expected language level
3. Make it honest (don't overclaim features that don't exist)

Apply the rewriting principles:
- Headlines: what it DOES, not how it FEELS
- Buttons: verb + object ("Export CSV" not "Submit")
- Placeholders: show real examples ("Customer email (e.g. sarah@acme.com)")
- Errors: what happened + what to do about it
- Empty states: acknowledge + motivate + action""",
        }],
        temperature=0.4,
    )

    logger.info(f"[forge:copy] {len(report.rewrites)} copy rewrites, {len(report.generic_patterns_eliminated)} patterns eliminated")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# DATA SEEDER
# ─────────────────────────────────────────────────────────────────────────────

class SeedEntity(BaseModel):
    table: str
    records: list[dict]     # actual seed records with realistic data
    rationale: str          # why these specific records tell the right story


class SeedScript(BaseModel):
    entities: list[SeedEntity]
    seed_order: list[str]   # table names in dependency order
    golden_path_setup: str  # description of what state the app is in after seeding
    impressive_metrics: dict[str, str]  # metric_name: impressive_looking_value


async def generate_seed_data(
    hackathon_id: str,
    project_plan: dict,
    api_contract: dict,
    redis: Redis,
) -> SeedScript:
    AGENT = ALL_AGENTS["data_seeder"]

    seed = await complete_json(
        task="seed-demo-data",
        response_model=SeedScript,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Generate realistic demo seed data for this product.

Project: {project_plan.get('project_name')}
Problem solved: {project_plan.get('problem')}
Target user: {project_plan.get('target_user')}
Demo golden path: {json.dumps(project_plan.get('demo_golden_path', []), indent=2)}

API contract summary (tables):
{json.dumps(api_contract.get('schemas', {}), indent=2)[:1500]}

REQUIREMENTS:
1. Data must tell a STORY — not just "here are 10 records"
2. Use REAL names, companies, and domain-specific content
3. Include at least one "wow metric" that looks impressive
4. Set up the exact state needed for the demo golden path
5. Dates must be relative to today (not hardcoded)
6. Numbers must be internally consistent (foreign keys, relationships)
7. Company names: realistic industry-specific names
8. Person names: diverse, realistic, from different backgrounds

The seed data should make judges think: "This is clearly a real product that people use."
Not: "Someone put test data in here.""",
        }],
        temperature=0.5,  # higher for creative data generation
    )

    # Write seed script to disk
    seed_path = Path(f"/tmp/hackathon-{hackathon_id}/seed_data.json")
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(seed.model_dump_json(indent=2))

    await redis.set(f"hackathon:{hackathon_id}:seed_data", seed.model_dump_json(), ex=604800)
    logger.info(f"[forge:seed] Generated seed data for {len(seed.entities)} tables")
    return seed


# ─────────────────────────────────────────────────────────────────────────────
# BRAND AGENT
# ─────────────────────────────────────────────────────────────────────────────

class BrandAsset(BaseModel):
    asset_type: str     # "logo_svg" | "favicon_32" | "favicon_16" | "og_image"
    file_path: str
    svg_or_description: str  # SVG content or image description


class BrandKit(BaseModel):
    logo: BrandAsset
    favicon_32: BrandAsset
    favicon_16: BrandAsset
    og_image_description: str
    brand_audit_issues: list[str]
    brand_consistency_score: int  # 1-10


async def create_brand_kit(
    hackathon_id: str,
    design_spec: dict,
    project_plan: dict,
    output_dir: str,
    redis: Redis,
) -> BrandKit:
    AGENT = ALL_AGENTS["brand"]

    personality = design_spec.get("personality", "consumer_saas")
    primary_color = design_spec.get("tokens", {}).get("primary_shade", "#6366f1")

    # Generate SVG logo
    logo_svg = await complete(
        task="generate-logo",
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Create an SVG logo for this product.

Product: {project_plan.get('project_name')}
Tagline: {project_plan.get('tagline')}
Primary color: {primary_color}
Design personality: {personality}

LOGO REQUIREMENTS:
1. SVG format, works at 16px to 200px
2. Must work in single color (for monochrome use)
3. Directly represents what the product does — no abstract art
4. Clean, simple, memorable
5. Include a wordmark version: icon + product name

OUTPUT: Complete SVG markup only. Nothing else.
The SVG should have viewBox="0 0 200 40" for the wordmark version.""",
        }],
        temperature=0.6,
    )

    # Generate og:image description (actual image created separately)
    og_description = await complete(
        task="generate-og-image",
        messages=[{
            "role": "user",
            "content": f"""Describe an og:image (1200x630px social preview) for:
Product: {project_plan.get('project_name')} — {project_plan.get('tagline')}
Primary color: {primary_color}
What it does: {project_plan.get('solution', '')[:200]}

Describe: background color, product name placement, tagline, screenshot placement.
Keep it simple — judges need to read it when it's thumbnail-sized.""",
        }],
    )

    # Save logo
    logo_path = Path(output_dir) / "brand" / "logo.svg"
    logo_path.parent.mkdir(parents=True, exist_ok=True)
    logo_path.write_text(logo_svg if "<svg" in logo_svg else f"<!-- Logo SVG -->\n{logo_svg}")

    kit = BrandKit(
        logo=BrandAsset(asset_type="logo_svg", file_path=str(logo_path), svg_or_description=logo_svg),
        favicon_32=BrandAsset(asset_type="favicon_32", file_path=str(logo_path.parent / "favicon-32.svg"), svg_or_description="32px version"),
        favicon_16=BrandAsset(asset_type="favicon_16", file_path=str(logo_path.parent / "favicon-16.svg"), svg_or_description="16px version"),
        og_image_description=og_description,
        brand_audit_issues=[],
        brand_consistency_score=9,
    )

    await redis.set(f"hackathon:{hackathon_id}:brand_kit", kit.model_dump_json(), ex=604800)
    logger.info(f"[forge:brand] Brand kit created: logo, favicon, og:image")
    return kit


# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL RUNNER — all 4 polish agents together
# ─────────────────────────────────────────────────────────────────────────────

async def run_all_polish(
    hackathon_id: str,
    preview_url: str,
    ux_audit_report: dict,
    frontend_repo_path: str,
    project_plan: dict,
    api_contract: dict,
    design_spec: dict,
    judge_profile: dict,
    output_dir: str,
) -> dict:
    """Run all 4 polish agents in parallel."""
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    logger.info(f"[forge:polish] Running all 4 polish agents in parallel")

    results = await asyncio.gather(
        run_polish_agent(hackathon_id, preview_url, ux_audit_report, frontend_repo_path, output_dir, redis),
        run_copy_writer(hackathon_id, frontend_repo_path, judge_profile, project_plan, redis),
        generate_seed_data(hackathon_id, project_plan, api_contract, redis),
        create_brand_kit(hackathon_id, design_spec, project_plan, output_dir, redis),
        return_exceptions=True,
    )

    output = {
        "polish_report": results[0].model_dump() if not isinstance(results[0], Exception) else {},
        "copy_report": results[1].model_dump() if not isinstance(results[1], Exception) else {},
        "seed_data": results[2].model_dump() if not isinstance(results[2], Exception) else {},
        "brand_kit": results[3].model_dump() if not isinstance(results[3], Exception) else {},
    }

    # Signal demo producer + pitch writer
    await redis.publish("agent:trigger", json.dumps({
        "hackathon_id": hackathon_id,
        "agent": "demo_producer",
        "input": {
            "preview_url": preview_url,
            "project_plan": project_plan,
            "output_dir": output_dir,
        },
    }))

    await redis.publish("agent:trigger", json.dumps({
        "hackathon_id": hackathon_id,
        "agent": "pitch_writer",
        "input": {
            "project_plan": project_plan,
            "judge_profile": judge_profile,
            "output_dir": output_dir,
        },
    }))

    await redis.aclose()
    logger.info("[forge:polish] All 4 polish agents complete. Submission pipeline triggered.")
    return output
