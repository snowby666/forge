# -*- coding: utf-8 -*-
"""
UI/UX Designer Agent
====================
The most critical agent in the system. Everything else depends on getting the
design right before any code is written.

This agent produces:
  - DesignSpec       — complete screen architecture
  - DesignTokens     — all design variables in TypeScript
  - ComponentSpecs   — every component with all states specified
  - DESIGN.md        — consumed by frontend engineer

It enforces the design constitution and rejects generic outputs.

CURSOR: This agent runs after concept approval and design approval checkpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp
from pydantic import BaseModel, Field, field_validator

from config.electronhub import complete, complete_json
from config.redis_client import get_redis
from config.agents_config import ALL_AGENTS
from config.forge_trace import trace_op, register_artifact, set_agent_context
from config.design_constitution import (
    ANTI_SLOP_RULES,
    STATIC_DESIGN_LAWS,
    DESIGN_CRITIQUE_RUBRIC,
    DESIGN_PERSONALITIES,
    DesignTokens,
)

logger = logging.getLogger(__name__)
AGENT = ALL_AGENTS["ui_ux_designer"]

BROWSER_URL = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")


# ── Pydantic output models ────────────────────────────────────────────────────

class ComponentVariant(BaseModel):
    name: str                   # e.g. "primary", "secondary", "destructive"
    tailwind_classes: str       # exact Tailwind classes for this variant
    description: str


class ComponentState(BaseModel):
    state: str                  # "default" | "hover" | "focus" | "active" | "disabled" | "loading" | "error"
    tailwind_classes: str       # additional classes for this state
    description: str


class ComponentSpec(BaseModel):
    name: str                   # PascalCase
    file_path: str              # e.g. "components/ui/status-badge.tsx"
    description: str
    purpose: str                # why this component exists in the product
    shadcn_base: str            # shadcn/ui component to build from (or "custom")
    variants: list[ComponentVariant]
    states: list[ComponentState]
    props_interface: str        # TypeScript interface as string
    default_props: dict[str, Any]
    real_copy: dict[str, Any]   # {"placeholder": "Search customers by name...", "label": "Customer"}
    accessibility_notes: str

    @field_validator("real_copy", mode="before")
    @classmethod
    def _coerce_copy_values(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            return v
        return {k: json.dumps(val) if not isinstance(val, str) else val for k, val in v.items()}
    is_demo_critical: bool      # must work perfectly for the demo path
    estimated_minutes: int      # honest estimate for frontend engineer


class ScreenSpec(BaseModel):
    route: str                  # e.g. "/dashboard"
    name: str
    purpose: str
    information_hierarchy: list[str]  # ordered list: "1. Status metrics, 2. Recent activity..."
    primary_action: str         # the ONE most important action on this screen
    secondary_actions: list[str]
    components: list[str]       # component names in render order
    layout_description: str     # prose describing the layout
    demo_path_position: int | None  # position in demo path (1=first, None=not on demo path)
    is_demo_entry: bool         # this is where judges land first
    empty_state: str            # what shows when there's no data
    loading_state: str          # what shows while data loads


class UserFlow(BaseModel):
    step: int
    action: str
    screen: str
    ui_element: str
    expected_outcome: str
    wow_moment: bool            # is this the moment that creates the emotional response?


class DesignSpec(BaseModel):
    personality: str            # key from DESIGN_PERSONALITIES
    personality_rationale: str  # why this personality was chosen for this product+judges
    design_token_rationale: str # why these specific colors/fonts
    screens: list[ScreenSpec]
    components: list[ComponentSpec]
    user_flow: list[UserFlow]
    demo_entry_route: str
    demo_total_steps: int
    anti_slop_self_check: list[str]  # specific anti-slop rules this design avoids


class DesignTokensOutput(BaseModel):
    """Full design token specification as a TypeScript const export."""
    typescript_content: str     # complete design-tokens.ts file content
    tailwind_config_extension: str  # theme.extend content for tailwind.config.ts
    css_variables: str          # :root CSS variables


# ── Google Stitch integration (MCP protocol) ──────────────────────────────────
# Stitch uses MCP at stitch.googleapis.com/mcp, auth via x-goog-api-key header.
# Keys from https://stitch.withgoogle.com/settings — set STITCH_API_KEY in .env.
# Not all keys support tool calls; we probe at startup and keep only valid ones.

STITCH_MCP_URL = "https://stitch.googleapis.com/mcp"

_stitch_keys: list[str] = []
_stitch_idx = 0
_stitch_validated = False
_stitch_lock = asyncio.Lock()


def _load_stitch_keys() -> list[str]:
    raw = (
        os.environ.get("STITCH_API_KEY")
        or os.environ.get("GOOGLE_STITCH_TOKENS")
        or ""
    )
    return [k.strip() for k in raw.split(",") if k.strip()]


async def _get_stitch_key() -> str | None:
    """Round-robin across validated Stitch API keys (lock-protected)."""
    global _stitch_keys, _stitch_idx, _stitch_validated
    async with _stitch_lock:
        if not _stitch_validated:
            _stitch_keys = _load_stitch_keys()
            _stitch_validated = True
        if not _stitch_keys:
            return None
        key = _stitch_keys[_stitch_idx % len(_stitch_keys)]
        _stitch_idx = (_stitch_idx + 1) % len(_stitch_keys)
        return key


async def _remove_stitch_key(bad_key: str) -> None:
    """Remove a key that returned 401 so we don't retry it."""
    global _stitch_keys
    async with _stitch_lock:
        _stitch_keys = [k for k in _stitch_keys if k != bad_key]


async def call_google_stitch(prompt: str, personality: str) -> list[dict]:
    """Generate a design screen via Google Stitch MCP API with key rotation.

    Performs the full flow in a single MCP session: create_project →
    generate_screen_from_text. Rotates to the next key on 401 errors.
    """
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import httpx
    except ImportError:
        logger.info("[forge:design] `mcp` package not installed — skipping Stitch")
        return []

    api_key = await _get_stitch_key()
    if not api_key:
        logger.info("[forge:design] No STITCH_API_KEY set — skipping Stitch, using LLM fallback")
        return []

    personality_data = DESIGN_PERSONALITIES.get(personality, {})
    full_prompt = (
        f"{prompt}. "
        f"Aesthetic: {personality_data.get('description', '')}. "
        f"Background: {personality_data.get('background_base', '#ffffff')}. "
        f"IMPORTANT: {personality_data.get('accent_style', 'clean and professional')}. "
        f"AVOID: {', '.join(personality_data.get('anti_patterns', []))}."
    )

    max_attempts = min(len(_stitch_keys), 5) or 1

    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(
                headers={"x-goog-api-key": api_key},
                timeout=httpx.Timeout(300.0, connect=15.0),
            ) as http:
                async with streamable_http_client(STITCH_MCP_URL, http_client=http) as (
                    read_stream, write_stream, _get_sid,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()

                        proj_result = await session.call_tool(
                            "create_project", {"title": f"forge-{os.getpid()}"}
                        )
                        if proj_result.isError:
                            logger.warning("[forge:design] Stitch create_project error: %s", proj_result.content)
                            api_key = await _get_stitch_key() or api_key
                            continue

                        project_id = ""
                        for block in proj_result.content:
                            if hasattr(block, "text"):
                                data = json.loads(block.text)
                                project_id = str(
                                    data.get("projectId")
                                    or data.get("id")
                                    or data.get("name", "").split("/")[-1]
                                )

                        if not project_id:
                            logger.warning("[forge:design] Stitch: no project ID returned")
                            api_key = await _get_stitch_key() or api_key
                            continue

                        logger.info("[forge:design] Stitch project created: %s", project_id)

                        screen_result = await session.call_tool(
                            "generate_screen_from_text",
                            {
                                "projectId": project_id,
                                "prompt": full_prompt,
                                "deviceType": "DESKTOP",
                            },
                        )

                        if screen_result.isError:
                            logger.warning("[forge:design] Stitch generate_screen error: %s", screen_result.content)
                            return []

                        screens = []
                        for block in screen_result.content:
                            if not hasattr(block, "text"):
                                continue
                            try:
                                data = json.loads(block.text)
                            except json.JSONDecodeError:
                                continue
                            components = data.get("outputComponents", [])
                            for comp in components:
                                screen_data = comp.get("screen", {})
                                if not screen_data:
                                    continue
                                screens.append({
                                    "id": screen_data.get("name", "").split("/")[-1],
                                    "html_url": screen_data.get("htmlCode", {}).get("downloadUrl", ""),
                                    "image_url": screen_data.get("screenshot", {}).get("downloadUrl", ""),
                                    "prompt": full_prompt,
                                })
                            for comp in components:
                                ds = comp.get("designSystem", {}).get("designSystem", {})
                                if ds:
                                    screens.append({"_design_system": ds})

                        logger.info("[forge:design] Google Stitch generated %d screens", len(screens))
                        try:
                            from config.forge_trace import emit_span
                            await emit_span(
                                hackathon_id="", agent_id="ui_ux_designer",
                                op="mcp", name="stitch:generate_screens",
                                span_input={"prompt": full_prompt[:200], "project_id": project_id},
                                span_output={"screen_count": len(screens), "image_urls": [s.get("image_url", "") for s in screens if s.get("image_url")]},
                            )
                        except Exception:
                            pass
                        return screens

        except (ExceptionGroup, BaseExceptionGroup) as eg:
            is_401 = any("401" in str(exc) for exc in (eg.exceptions if hasattr(eg, "exceptions") else [eg]))
            if is_401:
                logger.debug("[forge:design] Stitch key %s...%s returned 401, rotating", api_key[:8], api_key[-4:])
                await _remove_stitch_key(api_key)
                api_key = await _get_stitch_key()
                if not api_key:
                    logger.warning("[forge:design] All Stitch keys exhausted (401)")
                    return []
                continue
            logger.warning("[forge:design] Stitch ExceptionGroup: %s", eg)
            return []
        except asyncio.TimeoutError:
            logger.warning("[forge:design] Stitch timed out (attempt %d/%d)", attempt + 1, max_attempts)
            api_key = await _get_stitch_key() or api_key
        except Exception as e:
            logger.warning("[forge:design] Stitch error: %s", e)
            api_key = await _get_stitch_key() or api_key

    return []


# ── Figma MCP integration ─────────────────────────────────────────────────────

async def sync_to_figma(design_spec: DesignSpec, tokens: DesignTokensOutput) -> str | None:
    """Sync design spec to Figma via MCP."""
    figma_token = os.environ.get("FIGMA_ACCESS_TOKEN")
    figma_file_id = os.environ.get("FIGMA_FILE_ID")

    if not figma_token or not figma_file_id:
        logger.warning("[forge:design] Figma credentials not set")
        return None

    redis = get_redis()
    await redis.publish("figma:write", json.dumps({
        "file_id": figma_file_id,
        "design_spec": design_spec.model_dump(),
        "tokens": tokens.model_dump(),
    }))
    await redis.aclose()
    return figma_file_id


# ── Design spec generation ────────────────────────────────────────────────────

async def select_personality(project_plan: dict, judge_profile: dict) -> str:
    """Select the optimal design personality based on project type and judges."""
    class PersonalityChoice(BaseModel):
        personality: str
        rationale: str

    choice = await complete_json(
        task="design-system-create",
        response_model=PersonalityChoice,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Select the design personality for this project.

Project: {project_plan.get('project_name')}
Solution: {project_plan.get('solution')}
Target user: {project_plan.get('target_user')}
Core features: {json.dumps(project_plan.get('core_features', [])[:2], indent=2)}

Judge panel background:
{json.dumps(judge_profile, indent=2)}

Available personalities:
{json.dumps({k: v['description'] for k, v in DESIGN_PERSONALITIES.items()}, indent=2)}

Choose the personality that:
1. Fits the product type (a developer tool shouldn't look like a consumer app)
2. Will resonate with the judge panel's background
3. Differentiates from generic hackathon UI

Respond with the personality KEY (exactly as shown) and a 2-sentence rationale.""",
        }],
        temperature=0.3,
    )
    return choice.personality


async def generate_design_tokens(
    project_plan: dict,
    personality: str,
    hackathon_brief: dict,
) -> DesignTokensOutput:
    """Generate complete design token system."""
    personality_data = DESIGN_PERSONALITIES.get(personality, {})

    class RawTokens(BaseModel):
        primary_hue: int = Field(description="HSL hue 0-360")
        primary_shade: str
        primary_foreground: str
        secondary_shade: str
        secondary_foreground: str
        background_base: str
        background_surface: str
        background_raised: str
        foreground_primary: str
        foreground_secondary: str
        foreground_tertiary: str
        border_default: str
        border_emphasis: str
        semantic_success: str
        semantic_warning: str
        semantic_error: str
        semantic_info: str
        font_sans: str
        font_mono: str
        rationale: str

    raw = await complete_json(
        task="generate-color-palette",
        response_model=RawTokens,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Design the complete color and typography system for:

Project: {project_plan.get('project_name')} — {project_plan.get('solution')}
Personality: {personality} ({personality_data.get('description', '')})
Background base: {personality_data.get('background_base', 'your choice')}

RULES:
- Primary color: ONE precise brand color. NOT blue unless clearly justified.
- Justify your color psychologically: what emotion does it convey and why is that right?
- Background: {personality_data.get('background_base', 'your choice')} (use this exact value)
- Foreground: must have ≥ 4.5:1 contrast ratio against background
- No pure #000000 or #ffffff — use near-blacks and warm whites
- Font: {personality_data.get('font_sans', 'your choice')} (respect personality)

Hackathon theme context: {hackathon_brief.get('theme', 'general tech')}""",
        }],
        temperature=0.5,
    )

    # Generate the TypeScript design tokens file
    ts_content = await complete(
        task="generate-design-tokens",
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Generate a complete design-tokens.ts file for this project.

Raw token values:
{raw.model_dump_json(indent=2)}

Output a complete TypeScript file with:
1. A `tokens` const object with all design values
2. A `cn` export that wraps clsx+tailwind-merge
3. Type exports for all variant types
4. CSS variable declarations as a string constant

The file should be importable in any component:
import {{ tokens, type ColorToken, type SizeToken }} from '@/lib/tokens'""",
        }],
        temperature=0.1,
    )

    tailwind_config = await complete(
        task="generate-design-tokens",
        messages=[{
            "role": "user",
            "content": f"""Generate the Tailwind CSS theme.extend config for these tokens:
{raw.model_dump_json(indent=2)}

Output ONLY the JavaScript object that goes inside theme: {{ extend: {{ ... }} }}.
Include: colors, fontFamily, spacing, borderRadius, boxShadow, transitionDuration, transitionTimingFunction.""",
        }],
        temperature=0.1,
    )

    css_vars = await complete(
        task="generate-design-tokens",
        messages=[{
            "role": "user",
            "content": f"""Generate the CSS :root variables for these tokens:
{raw.model_dump_json(indent=2)}

Output ONLY the :root {{ ... }} block and the .dark {{ ... }} block for dark mode.
Follow shadcn/ui CSS variable naming convention.""",
        }],
        temperature=0.1,
    )

    return DesignTokensOutput(
        typescript_content=ts_content,
        tailwind_config_extension=tailwind_config,
        css_variables=css_vars,
    )


async def generate_screen_and_components(
    project_plan: dict,
    personality: str,
    tokens_output: DesignTokensOutput,
    stitch_screens: list[dict],
    extra_constraints: str = "",
) -> tuple[list[ScreenSpec], list[ComponentSpec]]:
    """Generate all screen and component specifications."""

    class ScreensAndComponents(BaseModel):
        screens: list[ScreenSpec]
        components: list[ComponentSpec]
        user_flow: list[UserFlow]
        anti_slop_self_check: list[str]

    result = await complete_json(
        task="write-component-spec",
        response_model=ScreensAndComponents,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Generate the complete screen architecture and component library.

Project: {project_plan.get('project_name')}
Core features (MAX 2): {json.dumps(project_plan.get('core_features', [])[:2], indent=2)}
Demo flow steps: {json.dumps(project_plan.get('demo_flow', []), indent=2)}
Demo mode: {project_plan.get('demo_mode_description', 'No auth required')}
Personality: {personality}
Design tokens available: See tailwind config below.

{ANTI_SLOP_RULES}

{STATIC_DESIGN_LAWS}

REQUIREMENTS:
1. Screens: exactly the screens needed for the demo path + 1-2 supporting screens
2. Components: ONLY components needed for those screens (no "nice to have")
3. Every component must have ALL states: default, hover, focus, active, disabled, loading, error, empty
4. Every component must have real copy — no "placeholder text" anywhere
5. Mark is_demo_critical: true on components that appear in the demo path
6. Set demo_path_position on screens to indicate order

ANTI-SLOP SELF-CHECK:
List which specific anti-slop rules this design avoids (be specific, not generic).

Stitch design references available: {len(stitch_screens)} screens generated.
{extra_constraints}""",
        }],
        temperature=0.3,
    )

    return result.screens, result.components


# ── File output ────────────────────────────────────────────────────────────────

def write_design_md(
    design_spec: DesignSpec,
    tokens: DesignTokensOutput,
    output_dir: str,
) -> str:
    """Write DESIGN.md for frontend engineer consumption."""
    output_path = Path(output_dir) / "DESIGN.md"

    lines = [
        f"# Design system — {design_spec.personality.replace('_', ' ').title()} aesthetic\n",
        f"**Personality rationale:** {design_spec.personality_rationale}\n",
        f"**Design token rationale:** {design_spec.design_token_rationale}\n",
        "\n## Anti-slop guarantees\n",
        "This design intentionally avoids:\n",
        *[f"- {rule}" for rule in design_spec.anti_slop_self_check],
        "\n---\n",
        "\n## Design tokens (use these, never hardcode values)\n",
        "```typescript",
        "// Import from @/lib/tokens",
        tokens.typescript_content[:500] + "...",
        "```\n",
        "\n## Screen architecture\n",
    ]

    for screen in sorted(design_spec.screens, key=lambda s: s.demo_path_position or 99):
        entry = " ← DEMO ENTRY" if screen.is_demo_entry else ""
        demo_pos = f" (Demo step {screen.demo_path_position})" if screen.demo_path_position else ""
        lines.extend([
            f"\n### `{screen.route}` — {screen.name}{entry}{demo_pos}",
            f"**Purpose:** {screen.purpose}",
            f"\n**Information hierarchy:**",
            *[f"{i+1}. {item}" for i, item in enumerate(screen.information_hierarchy)],
            f"\n**Primary action:** {screen.primary_action}",
            f"**Secondary actions:** {', '.join(screen.secondary_actions) or 'none'}",
            f"\n**Layout:** {screen.layout_description}",
            f"\n**Empty state:** {screen.empty_state}",
            f"**Loading state:** {screen.loading_state}",
            f"\n**Components used:** {', '.join(screen.components)}",
        ])

    lines.extend(["\n---\n", "\n## Component specifications\n"])

    for comp in sorted(design_spec.components, key=lambda c: (not c.is_demo_critical, c.name)):
        critical = " 🔴 DEMO CRITICAL" if comp.is_demo_critical else ""
        lines.extend([
            f"\n### `{comp.name}`{critical}",
            f"**File:** `{comp.file_path}`",
            f"**Purpose:** {comp.purpose}",
            f"**shadcn/ui base:** `{comp.shadcn_base}`",
            f"**Est. implementation:** {comp.estimated_minutes} min",
            f"\n**Props:**",
            f"```typescript",
            comp.props_interface,
            f"```",
            f"\n**Real copy:**",
            *[f"- `{k}`: `\"{v}\"`" for k, v in comp.real_copy.items()],
            f"\n**Variants:**",
            *[f"- `{v.name}`: {v.description} — `{v.tailwind_classes}`" for v in comp.variants],
            f"\n**All states to implement:**",
            *[f"- `{s.state}`: {s.description} — `{s.tailwind_classes}`" for s in comp.states],
            f"\n**Accessibility:** {comp.accessibility_notes}",
        ])

    lines.extend([
        "\n---\n",
        "\n## 90-second demo path\n",
        f"**Demo entry:** `{design_spec.demo_entry_route}`\n",
        f"**Total steps:** {design_spec.demo_total_steps}\n",
    ])

    for step in design_spec.user_flow:
        wow = " ⭐ WOW MOMENT" if step.wow_moment else ""
        lines.append(f"{step.step}. **{step.action}**{wow}")
        lines.append(f"   Screen: `{step.screen}` | Element: `{step.ui_element}`")
        lines.append(f"   Expected: {step.expected_outcome}")

    output_path.write_text("\n".join(lines))
    logger.info(f"[forge:design] DESIGN.md written: {len(lines)} lines")
    return str(output_path)


def write_design_tokens_ts(tokens: DesignTokensOutput, output_dir: str) -> str:
    """Write the TypeScript design tokens file."""
    tokens_path = Path(output_dir) / "design-tokens.ts"
    tokens_path.write_text(tokens.typescript_content)
    return str(tokens_path)


def write_component_specs_json(specs: list[ComponentSpec], output_dir: str) -> str:
    """Write component specs as JSON for frontend engineer."""
    specs_path = Path(output_dir) / "component-specs.json"
    specs_path.write_text(
        json.dumps([s.model_dump() for s in specs], indent=2)
    )
    return str(specs_path)


# ── Design critique ────────────────────────────────────────────────────────────

async def critique_own_design(design_spec: DesignSpec) -> dict:
    """Have the agent critique its own design against the rubric before publishing."""
    class SelfCritique(BaseModel):
        first_impression_score: int
        visual_polish_score: int
        interaction_quality_score: int
        content_realism_score: int
        demo_path_clarity_score: int
        brand_coherence_score: int
        overall_score: float
        issues_found: list[str]
        approved: bool

    critique = await complete_json(
        task="critique-design",
        response_model=SelfCritique,
        system_prompt=AGENT.system_prompt,
        messages=[{
            "role": "user",
            "content": f"""Score this design against the critique rubric.

{DESIGN_CRITIQUE_RUBRIC}

Design to evaluate:
- Personality: {design_spec.personality}
- Screens: {[s.name for s in design_spec.screens]}
- Anti-slop self-check: {design_spec.anti_slop_self_check}
- Demo entry: {design_spec.demo_entry_route}
- Component count: {len(design_spec.components)}
- Demo-critical components: {sum(1 for c in design_spec.components if c.is_demo_critical)}

Be honest. If this design has anti-slop violations or would score < 7 in any dimension,
set approved=false and list specific issues.""",
        }],
        temperature=0.2,
    )

    if not critique.approved:
        logger.warning(f"[forge:design] Design self-critique failed. Score: {critique.overall_score}")
        logger.warning(f"[forge:design] Issues: {critique.issues_found}")

    return critique.model_dump()


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def run_ui_ux_agent(
    hackathon_id: str,
    project_plan: dict,
    judge_profile: dict,
    hackathon_brief: dict,
    output_dir: str,
) -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    set_agent_context(hackathon_id, "ui_ux_designer")

    logger.info(f"[forge:design] Starting design pipeline for: {project_plan.get('project_name')}")

    # Step 1: Select design personality
    async with trace_op("llm", "design:select_personality", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        personality = await select_personality(project_plan, judge_profile)
        _sp.output = {"personality": personality}
    logger.info(f"[forge:design] Selected personality: {personality}")

    # Step 2: Generate design tokens
    async with trace_op("llm", "design:generate_tokens", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        tokens = await generate_design_tokens(project_plan, personality, hackathon_brief)
        _sp.output = {
            "has_typescript": bool(tokens.typescript_content),
            "has_tailwind": bool(tokens.tailwind_config_extension),
            "has_css": bool(tokens.css_variables),
        }

    # Step 3: Generate screens via Google Stitch (or fallback)
    concept_summary = (
        f"{project_plan.get('project_name')}: {project_plan.get('solution')}. "
        f"Core features: {', '.join(f['name'] for f in project_plan.get('core_features', [])[:2])}"
    )
    async with trace_op("mcp", "design:stitch_screens", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        _sp.input = {"concept": concept_summary[:200], "personality": personality}
        stitch_screens = await call_google_stitch(concept_summary, personality)
        _sp.output = {"screen_count": len(stitch_screens), "image_urls": [s.get("image_url", "") for s in stitch_screens if s.get("image_url")]}
    logger.info(f"[forge:design] Google Stitch generated {len(stitch_screens)} screens")

    # Step 4: Generate full design spec
    async with trace_op("llm", "design:screen_and_components", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        screens, components = await generate_screen_and_components(
            project_plan, personality, tokens, stitch_screens
        )
        _sp.output = {"screens": len(screens), "components": len(components)}

    design_spec = DesignSpec(
        personality=personality,
        personality_rationale="",  # filled during generation
        design_token_rationale="",  # filled during generation
        screens=screens,
        components=components,
        user_flow=[],  # filled during generation
        demo_entry_route=next((s.route for s in screens if s.is_demo_entry), "/"),
        demo_total_steps=sum(1 for s in screens if s.demo_path_position),
        anti_slop_self_check=[],  # filled during generation
    )

    # Step 5: Self-critique — iterate if score < 7.0
    max_critique_attempts = 2
    for attempt in range(max_critique_attempts):
        async with trace_op("llm", f"design:self_critique:attempt_{attempt+1}", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
            critique = await critique_own_design(design_spec)
            _sp.output = {"approved": critique.get("approved"), "score": critique.get("overall_score"), "issues": critique.get("issues_found", [])}
        if critique["approved"] or attempt == max_critique_attempts - 1:
            break

        logger.info(f"[forge:design] Design failed self-critique (score={critique.get('overall_score', 0):.1f}), iterating (attempt {attempt + 1})")
        issues = "\n".join(f"- {issue}" for issue in critique.get("issues_found", []))

        # Re-generate screens and components with specific fix constraints added
        async with trace_op("llm", f"design:regenerate_after_critique:{attempt+1}", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _rsp:
            _rsp.input = {"issues": issues[:500]}
            screens, components = await generate_screen_and_components(
                project_plan=project_plan,
                personality=personality,
                tokens_output=tokens,
                stitch_screens=stitch_screens,
                extra_constraints=f"""PREVIOUS CRITIQUE FAILED — FIX THESE SPECIFIC ISSUES BEFORE ANYTHING ELSE:

{issues}

Critique scores:
- Reference site match: {critique.get('first_impression_score', 0)}/10
- Visual polish: {critique.get('visual_polish_score', 0)}/10
- Interaction quality: {critique.get('interaction_quality_score', 0)}/10
- Content realism: {critique.get('content_realism_score', 0)}/10
- Demo path clarity: {critique.get('demo_path_clarity_score', 0)}/10
- Brand coherence: {critique.get('brand_coherence_score', 0)}/10

Do NOT repeat the same design decisions that caused these failures.""",
            )
            _rsp.output = {"screens": len(screens), "components": len(components)}

        design_spec = DesignSpec(
            personality=personality,
            personality_rationale=design_spec.personality_rationale,
            design_token_rationale=design_spec.design_token_rationale,
            screens=screens,
            components=components,
            user_flow=design_spec.user_flow,
            demo_entry_route=next((s.route for s in screens if s.is_demo_entry), "/"),
            demo_total_steps=sum(1 for s in screens if s.demo_path_position),
            anti_slop_self_check=design_spec.anti_slop_self_check,
        )

    # Step 6: Sync to Figma
    figma_id: str | None = None
    async with trace_op("redis", "design:sync_to_figma", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        figma_id = await sync_to_figma(design_spec, tokens)
        _sp.output = {"figma_file_id": figma_id}
    if figma_id:
        logger.info(f"[forge:design] Synced to Figma: {figma_id}")

    # Step 7: Write output files
    async with trace_op("file", "design:write_design_md", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        design_md_path = write_design_md(design_spec, tokens, output_dir)
        _sp.output = {"path": design_md_path, "screens": len(design_spec.screens), "components": len(design_spec.components)}
    await register_artifact(hackathon_id, "ui_ux_designer", "DESIGN.md", "markdown", f"Design specification — {len(design_spec.screens)} screens, {len(design_spec.components)} components")

    async with trace_op("file", "design:write_tokens_ts", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        tokens_path = write_design_tokens_ts(tokens, output_dir)
        _sp.output = {"path": tokens_path}
    await register_artifact(hackathon_id, "ui_ux_designer", "design-tokens.ts", "typescript", "Design tokens (colors, spacing, typography)")

    async with trace_op("file", "design:write_component_specs", hackathon_id=hackathon_id, agent_id="ui_ux_designer") as _sp:
        specs_path = write_component_specs_json(components, output_dir)
        _sp.output = {"path": specs_path, "component_count": len(components)}
    await register_artifact(hackathon_id, "ui_ux_designer", "component-specs.json", "json", f"Component specifications — {len(components)} components")

    result = {
        "design_spec": design_spec.model_dump(),
        "tokens": tokens.model_dump(),
        "output_dir": output_dir,
        "design_md_path": design_md_path,
        "tokens_path": tokens_path,
        "specs_path": specs_path,
        "figma_file_id": figma_id,
        "self_critique": critique,
        "personality": personality,
        "screen_count": len(screens),
        "component_count": len(components),
        "demo_critical_components": sum(1 for c in components if c.is_demo_critical),
    }

    logger.info(
        f"[forge:design] Design complete: {len(screens)} screens, {len(components)} components, "
        f"personality={personality}, critique_score={critique.get('overall_score')}"
    )

    return result


# ── Redis worker ──────────────────────────────────────────────────────────────

async def run_worker() -> None:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent:trigger")

    logger.info("[forge:design] Worker ready")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        payload = json.loads(message["data"])
        if payload.get("agent") != "ui_ux_designer":
            continue

        hackathon_id = payload["hackathon_id"]
        inp = payload["input"]

        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc).isoformat()
        set_agent_context(hackathon_id, "ui_ux_designer")
        await redis.set(f"task:{hackathon_id}:ui_ux_designer", json.dumps({
            "status": "in-progress",
            "started_at": started_at,
        }), ex=604800)

        try:
            output_dir = f"/tmp/hackathon-{hackathon_id}"
            result = await run_ui_ux_agent(
                hackathon_id=hackathon_id,
                project_plan=inp["project_plan"],
                judge_profile=inp.get("judge_profile", {}),
                hackathon_brief=inp.get("brief", {}),
                output_dir=output_dir,
            )
            import time as _t
            finished_at = datetime.now(timezone.utc).isoformat()
            await redis.set(
                f"task:{hackathon_id}:ui_ux_designer",
                json.dumps({
                    "status": "done",
                    "data": result,
                    "started_at": started_at,
                    "finished_at": finished_at,
                }),
                ex=604800,
            )
        except Exception as e:
            logger.error(f"[forge:design] Failed: {e}", exc_info=True)
            finished_at = datetime.now(timezone.utc).isoformat()
            await redis.set(
                f"task:{hackathon_id}:ui_ux_designer",
                json.dumps({
                    "status": "failed",
                    "error": str(e),
                    "started_at": started_at,
                    "finished_at": finished_at,
                }),
                ex=604800,
            )

    await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(run_worker())
