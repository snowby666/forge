"""
Knowledge Updater Agent
=======================
Layer 7: Infrastructure — runs weekly (or on-demand before a hackathon).

This agent does its own web research and UPDATES the living knowledge section of
config/design_constitution.py with current information on:
  - Trending UI component libraries and design tools
  - Current winning hackathon concept patterns
  - Frontend/backend stack recommendations
  - What aesthetic is impressing judges right now

It NEVER touches the static constitution sections (STATIC_DESIGN_LAWS, ANTI_SLOP_RULES,
REFERENCE_SITES, DESIGN_CRITIQUE_RUBRIC, COMPONENT_QUALITY_CHECKLIST, personalities,
DesignTokens, or agent system prompts). Those are frozen.

The boundary is clearly marked with:
  # KNOWLEDGE_UPDATER_SECTION_START
  # KNOWLEDGE_UPDATER_SECTION_END

CURSOR: Run manually with:
  python agents/python/infra/knowledge_updater.py

Or triggered by Commander before each new hackathon cycle.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from config.electronhub import complete_json
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CONSTITUTION_PATH = Path(__file__).parents[3] / "config" / "design_constitution.py"

SECTION_START = "# KNOWLEDGE_UPDATER_SECTION_START"
SECTION_END   = "# KNOWLEDGE_UPDATER_SECTION_END"


# ── Research models ────────────────────────────────────────────────────────────

class TrendingLibraries(BaseModel):
    primary: str
    primary_rationale: str
    secondary: str
    secondary_rationale: str
    tables: str
    charts: str
    icons: str
    forms: str
    animations: str
    streaming_ai: str
    avoid: list[str]


class WinningAesthetic(BaseModel):
    summary: str
    key_patterns: list[str]
    overused_avoid: list[str]


class WinningConcepts(BaseModel):
    what_wins: list[str]
    what_loses: list[str]
    red_flags: list[str]
    differentiation_strategies: list[str]


class FrontendStack(BaseModel):
    framework: str
    language: str
    styling: str
    components: str
    state: str
    forms: str
    tables: str
    animations: str
    streaming: str
    charts: str
    fonts: str
    deployment: str
    key_insight: str


class BackendStack(BaseModel):
    framework: str
    language: str
    orm: str
    database: str
    migrations: str
    validation: str
    auth: str
    deployment: str
    streaming: str
    key_insight: str


class LivingKnowledge(BaseModel):
    last_updated: str
    updated_by: str = "knowledge_updater_agent"
    trending_component_libraries: dict
    winning_aesthetic_2026: dict
    winning_concept_patterns_2026: dict
    frontend_stack_2026: dict
    backend_stack_2026: dict


# ── Web research ───────────────────────────────────────────────────────────────

async def _call_with_web_search(prompt: str, model: str = "claude-sonnet-4-5") -> str:
    """Call ElectronHub with web_search tool enabled for live research."""
    import json as _json
    import aiohttp as _aio

    api_key  = os.environ["ELECTRONHUB_API_KEY"]
    base_url = os.environ.get("ELECTRONHUB_BASE_URL", "https://api.electronhub.ai/v1")

    payload = {
        "model": model,
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}],
    }

    async with _aio.ClientSession() as session:
        async with session.post(
            f"{base_url.rstrip('/')}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=_aio.ClientTimeout(total=90),
        ) as resp:
            if resp.status != 200:
                # Fallback to plain complete() without web search
                return ""
            data = await resp.json()

    # Extract text from response (may include tool_use blocks)
    texts = [
        block["text"]
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    return " ".join(texts)


async def research_trending_libraries() -> TrendingLibraries:
    """Research current best React UI libraries via live web search."""
    year  = datetime.now().year
    month = datetime.now().strftime("%B %Y")

    prompt = f"""Search the web and answer: what are the best React UI libraries for developer tools in {month}?

Research specifically:
1. Best component library for Next.js + shadcn/ui projects (primary recommendation + backup)
2. Best data table library (TanStack Table still best? anything newer?)
3. Best chart library for dense data tools (Observable Plot? Recharts? D3?)
4. Best icon library in {year} (Lucide? Radix Icons? Phosphor?)
5. Best form validation library (React Hook Form + Zod still standard?)
6. Best animation (Framer Motion? CSS-only? anything new?)
7. Standard for streaming AI output in React (Vercel AI SDK useChat?)
8. What libraries to avoid — which became dated or deprecated in {year}?

Focus on: composio.dev / linear.app / hex.tech aesthetic. Dense, developer-native.
NOT consumer SaaS libraries. Be specific about versions and trade-offs."""

    raw = ""
    try:
        raw = await _call_with_web_search(prompt)
    except Exception as e:
        logger.warning(f"[forge:knowledge] Web search failed: {e} — using training knowledge")

    # Parse the text response into structured form
    result = await complete_json(
        task="research-sponsor-apis",
        response_model=TrendingLibraries,
        messages=[{
            "role": "user",
            "content": f"""Based on this research about React libraries in {month}, extract structured recommendations.

Research findings:
{raw if raw else "(web search unavailable — use best training knowledge)"}

Current date: {month}
Fill all fields with specific, opinionated recommendations.""",
        }],
        temperature=0.2,
    )
    return result


async def research_winning_concepts() -> WinningConcepts:
    """Research winning hackathon concepts via live web search."""
    year  = datetime.now().year
    month = datetime.now().strftime("%B %Y")

    prompt = f"""Search for: what AI agent project types are winning hackathons in {month}?
Look for recent hackathon results on Devpost, Lablab.ai, MLH, and Microsoft AI hackathons.
Find: what won, what lost, what judges rewarded, what concepts were overused."""
    raw = ""
    try:
        raw = await _call_with_web_search(prompt)
    except Exception as e:
        logger.warning(f"[forge:knowledge] Web search failed for concepts: {e}")

    result = await complete_json(
        task="analyze-competitors",
        response_model=WinningConcepts,
        messages=[{
            "role": "user",
            "content": f"""Based on this research, extract winning hackathon concept patterns in {month}.

Research:
{raw if raw else "(use best training knowledge)"}

What AI agent project TYPES are winning hackathons in {datetime.now().year}?

Research based on:
- Microsoft AI Agents Hackathon 2025 winners (RiskWise won $20k with supply chain risk analysis)
- Lablab.ai recent winners (GameForge AI, Prism, Stylin')
- NVIDIA NeMo hackathon winners
- General pattern of what's been winning in the last 12 months

Answer specifically:
1. What 6 types of AI agent projects are winning? (be specific, not generic)
2. What 6 types are losing / too generic?
3. What 6 red flags in a project description signal a loser?
4. What 4 differentiation strategies separate winners from generic?

Reference: Composio's tool-as-product aesthetic is winning. Generic chatbots are losing.
Agents that "close the loop" (read system A → decide → write system B) win.
Current date: {datetime.now().strftime('%B %Y')}""",
        }],
        temperature=0.4,
    )
    return result


async def research_winning_aesthetic() -> WinningAesthetic:
    """Research current winning design aesthetic for developer tools."""
    result = await complete_json(
        task="design-system-create",
        response_model=WinningAesthetic,
        messages=[{
            "role": "user",
            "content": f"""What UI/UX design patterns are winning hackathons for developer tools in {datetime.now().year}?

Reference companies to analyze:
- composio.dev: dense terminal aesthetic, code blocks as UI, inline tool badges
- hex.tech: data notebook, information density as luxury, SQL cells
- riff.ai: enterprise workflow, numbered steps, status everywhere
- linear.app: ultra-dark, keyboard-first, single accent

Research questions:
1. What specific UI patterns from these reference sites are being used by winning hackathon projects?
2. What overused patterns should be avoided in {datetime.now().year}?
3. What is the one-sentence summary of the winning aesthetic?

Be specific about components and patterns, not vague aesthetic adjectives.
Current date: {datetime.now().strftime('%B %Y')}""",
        }],
        temperature=0.3,
    )
    return result


async def research_frontend_stack() -> FrontendStack:
    """Research current best frontend stack for hackathon projects."""
    result = await complete_json(
        task="create-sprint-plan",
        response_model=FrontendStack,
        messages=[{
            "role": "user",
            "content": f"""What is the optimal frontend stack for a hackathon in {datetime.now().year}?

Constraints:
- Must deploy to Vercel (free tier)
- Must look like it came from a serious startup (not a class project)
- Must support real-time streaming AI output
- Must have data tables, forms, and status indicators
- Must work at 375px mobile

Research the current best options for:
- Framework (Next.js version?)
- Styling (Tailwind version? CSS-in-JS?)
- Component library (shadcn/ui? Anything newer?)
- State management (TanStack Query v? Zustand?)
- Forms (React Hook Form? Anything better?)
- Data tables (TanStack Table v?)
- Animations (Framer Motion? CSS only?)
- AI streaming (Vercel AI SDK? Custom?)
- Charts (Recharts? Observable Plot? Something newer?)
- Fonts (Geist? Inter? Anything new?)
- Deployment (Vercel still the best free option?)

Include a key_insight that is the ONE thing devs get wrong that makes their hackathon UI look bad.
Current date: {datetime.now().strftime('%B %Y')}""",
        }],
        temperature=0.2,
    )
    return result


async def research_backend_stack() -> BackendStack:
    """Research current best backend stack for hackathon projects."""
    result = await complete_json(
        task="create-sprint-plan",
        response_model=BackendStack,
        messages=[{
            "role": "user",
            "content": f"""What is the optimal Python backend stack for a hackathon in {datetime.now().year}?

Constraints:
- Must support streaming AI output (SSE)
- Must have zero auth complexity (use managed auth)
- Must deploy for free or near-free
- Must have no cold starts (killer for demo day)
- Python is mandatory (we use Python for all agents)

Research:
- Best Python web framework (FastAPI? Anything newer/better?)
- Best ORM (SQLAlchemy 2.0? Prisma Python? Anything better?)
- Best auth solution for minimal setup (Clerk? Something newer?)
- Best free deployment with no cold starts (Railway? Render? Fly.io?)
- Best way to handle AI streaming in FastAPI

Include a key_insight that is the ONE thing teams get wrong in their backend that
causes demo day failures.
Current date: {datetime.now().strftime('%B %Y')}""",
        }],
        temperature=0.2,
    )
    return result


# ── Update the constitution file ──────────────────────────────────────────────

def _serialize_to_python(obj) -> str:
    """Convert Python objects to clean Python literal syntax."""
    if isinstance(obj, dict):
        items = ",\n        ".join(
            f'"{k}": {_serialize_to_python(v)}' for k, v in obj.items()
        )
        return "{\n        " + items + "\n    }"
    elif isinstance(obj, list):
        items = ",\n            ".join(_serialize_to_python(v) for v in obj)
        return "[\n            " + items + ",\n        ]"
    elif isinstance(obj, str):
        # Escape quotes and use repr
        return repr(obj)
    else:
        return repr(obj)


def update_constitution(new_knowledge: LivingKnowledge) -> str:
    """
    Write the new LIVING_KNOWLEDGE dict into the design_constitution.py file.
    Only replaces the section between KNOWLEDGE_UPDATER_SECTION_START and _END.
    Everything outside that section is untouched.
    """
    content = CONSTITUTION_PATH.read_text()

    start_idx = content.find(SECTION_START)
    end_idx = content.find(SECTION_END)

    if start_idx == -1 or end_idx == -1:
        raise RuntimeError(f"Could not find knowledge updater section markers in {CONSTITUTION_PATH}")

    # Build the new section
    data = new_knowledge.model_dump()

    new_section_lines = [
        SECTION_START,
        "",
        "LIVING_KNOWLEDGE = {",
        f'    "last_updated": {repr(data["last_updated"])},',
        f'    "updated_by": {repr(data["updated_by"])},',
        "",
        '    "trending_component_libraries": {',
    ]

    libs = data["trending_component_libraries"]
    for k, v in libs.items():
        new_section_lines.append(f'        {repr(k)}: {_serialize_to_python(v)},')

    new_section_lines += [
        "    },",
        "",
        '    "winning_aesthetic_2026": {',
    ]

    aesthetic = data["winning_aesthetic_2026"]
    for k, v in aesthetic.items():
        new_section_lines.append(f'        {repr(k)}: {_serialize_to_python(v)},')

    new_section_lines += [
        "    },",
        "",
        '    "winning_concept_patterns_2026": {',
    ]

    concepts = data["winning_concept_patterns_2026"]
    for k, v in concepts.items():
        new_section_lines.append(f'        {repr(k)}: {_serialize_to_python(v)},')

    new_section_lines += [
        "    },",
        "",
        '    "frontend_stack_2026": {',
    ]

    fe = data["frontend_stack_2026"]
    for k, v in fe.items():
        new_section_lines.append(f'        {repr(k)}: {_serialize_to_python(v)},')

    new_section_lines += [
        "    },",
        "",
        '    "backend_stack_2026": {',
    ]

    be = data["backend_stack_2026"]
    for k, v in be.items():
        new_section_lines.append(f'        {repr(k)}: {_serialize_to_python(v)},')

    new_section_lines += [
        "    },",
        "}",
        "",
    ]

    new_section = "\n".join(new_section_lines)

    # Splice into original content
    before = content[:start_idx]
    after = content[end_idx + len(SECTION_END):]
    updated = before + new_section + SECTION_END + after

    return updated


def validate_update(new_content: str) -> bool:
    """Verify the updated file is valid Python and preserves static sections."""
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        logger.error(f"[forge:knowledge] Updated file has syntax error: {e}")
        return False

    # Verify key static sections still present
    required = [
        "STATIC_DESIGN_LAWS",
        "ANTI_SLOP_RULES",
        "DESIGN_PERSONALITIES",
        "DESIGN_CRITIQUE_RUBRIC",
        "COMPONENT_QUALITY_CHECKLIST",
        "SYSTEM_PROMPT_DESIGN_AGENT",
        "class DesignTokens",
        SECTION_START,
        SECTION_END,
    ]

    for marker in required:
        if marker not in new_content:
            logger.error(f"[forge:knowledge] Static section missing after update: {marker}")
            return False

    return True


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def run_knowledge_update(dry_run: bool = False) -> dict:
    """
    Run all 5 research tasks in parallel, then update the constitution.
    """
    logger.info("[forge:knowledge] Starting knowledge research (5 tasks in parallel)...")

    libs, concepts, aesthetic, fe_stack, be_stack = await asyncio.gather(
        research_trending_libraries(),
        research_winning_concepts(),
        research_winning_aesthetic(),
        research_frontend_stack(),
        research_backend_stack(),
        return_exceptions=True,
    )

    # Handle partial failures
    if isinstance(libs, Exception):
        logger.warning(f"[forge:knowledge] libs research failed: {libs}")
        libs = None
    if isinstance(concepts, Exception):
        logger.warning(f"[forge:knowledge] concepts research failed: {concepts}")
        concepts = None
    if isinstance(aesthetic, Exception):
        logger.warning(f"[forge:knowledge] aesthetic research failed: {aesthetic}")
        aesthetic = None
    if isinstance(fe_stack, Exception):
        logger.warning(f"[forge:knowledge] fe_stack research failed: {fe_stack}")
        fe_stack = None
    if isinstance(be_stack, Exception):
        logger.warning(f"[forge:knowledge] be_stack research failed: {be_stack}")
        be_stack = None

    # Read current knowledge to use as fallback for failed sections
    current_content = CONSTITUTION_PATH.read_text()
    current_start = current_content.find(SECTION_START)
    current_end = current_content.find(SECTION_END)
    current_section = current_content[current_start:current_end]

    # Build the new knowledge object (merge new + current fallbacks)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_knowledge = LivingKnowledge(
        last_updated=now,
        updated_by="knowledge_updater_agent",
        trending_component_libraries=libs.model_dump() if libs else _extract_current("trending_component_libraries", current_section),
        winning_aesthetic_2026=aesthetic.model_dump() if aesthetic else _extract_current("winning_aesthetic_2026", current_section),
        winning_concept_patterns_2026=concepts.model_dump() if concepts else _extract_current("winning_concept_patterns_2026", current_section),
        frontend_stack_2026=fe_stack.model_dump() if fe_stack else _extract_current("frontend_stack_2026", current_section),
        backend_stack_2026=be_stack.model_dump() if be_stack else _extract_current("backend_stack_2026", current_section),
    )

    if dry_run:
        logger.info("[forge:knowledge] Dry run — not writing to disk")
        return {"dry_run": True, "knowledge": new_knowledge.model_dump()}

    # Update the file
    updated_content = update_constitution(new_knowledge)

    if not validate_update(updated_content):
        raise RuntimeError("[forge:knowledge] Validation failed — NOT writing update to protect static sections")

    # Backup original
    backup_path = CONSTITUTION_PATH.with_suffix(".py.bak")
    backup_path.write_text(current_content)
    logger.info(f"[forge:knowledge] Backed up to {backup_path}")

    CONSTITUTION_PATH.write_text(updated_content)
    logger.info(f"[forge:knowledge] Knowledge updated successfully. Version: {now}")

    return {
        "updated": True,
        "date": now,
        "sections_updated": ["trending_component_libraries", "winning_aesthetic_2026",
                             "winning_concept_patterns_2026", "frontend_stack_2026", "backend_stack_2026"],
        "sections_preserved": ["STATIC_DESIGN_LAWS", "ANTI_SLOP_RULES", "DESIGN_PERSONALITIES",
                               "DESIGN_CRITIQUE_RUBRIC", "COMPONENT_QUALITY_CHECKLIST",
                               "system prompts", "DesignTokens"],
    }


def _extract_current(key: str, section_text: str) -> dict:
    """Extract a specific dict from the current LIVING_KNOWLEDGE section as fallback."""
    # Simple pattern: find the key and extract its value
    # This is a best-effort fallback — if it fails, the calling code handles it
    try:
        match = re.search(rf'"{key}":\s*\{{', section_text)
        if not match:
            return {}
        # Find the matching closing brace
        start = match.end() - 1
        depth = 0
        end = start
        for i, c in enumerate(section_text[start:], start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        value_str = section_text[start:end]
        return ast.literal_eval(value_str)
    except Exception:
        return {}


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Update design constitution living knowledge")
    parser.add_argument("--dry-run", action="store_true", help="Research without writing to disk")
    parser.add_argument("--show-current", action="store_true", help="Show current LIVING_KNOWLEDGE version")
    args = parser.parse_args()

    if args.show_current:
        content = CONSTITUTION_PATH.read_text()
        start = content.find(SECTION_START)
        end = content.find(SECTION_END)
        print(content[start:end + len(SECTION_END)])
    else:
        async def main():
            result = await run_knowledge_update(dry_run=args.dry_run)
            print(json.dumps(result, indent=2))

        asyncio.run(main())
