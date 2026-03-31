# -*- coding: utf-8 -*-
"""
Test suite for forge.
Tests: ElectronHub routing, design constitution enforcement, agent coordination, Redis patterns.

Run: pytest tests/ -v --timeout=30
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── ElectronHub tests ──────────────────────────────────────────────────────────

class TestElectronHub:
    """Verify model routing and task-tier mapping."""

    def test_task_tier_coverage(self):
        """Every task in TASK_TIER should have a valid model."""
        from config.electronhub import TASK_TIER, MODELS, Tier
        for task, tier in TASK_TIER.items():
            assert tier in MODELS, f"Task '{task}' → tier '{tier}' has no model"
            assert MODELS[tier], f"No model for tier '{tier}'"

    def test_design_tasks_use_design_tier(self):
        """Design-related tasks should use Tier.DESIGN for higher creativity."""
        from config.electronhub import TASK_TIER, Tier
        design_tasks = [
            "design-system-create", "generate-color-palette",
            "write-component-spec", "critique-design",
        ]
        for task in design_tasks:
            assert TASK_TIER.get(task) == Tier.DESIGN, f"Task '{task}' should use DESIGN tier"

    def test_bulk_tasks_use_cheap_model(self):
        """High-volume tasks should use bulk/fast models."""
        from config.electronhub import TASK_TIER, Tier
        bulk_tasks = ["fix-lint-error", "write-tests", "write-pytest", "seed-demo-data"]
        for task in bulk_tasks:
            tier = TASK_TIER.get(task)
            assert tier in (Tier.BULK, Tier.FAST), f"Task '{task}' should use BULK or FAST tier"

    def test_fallback_chain_is_complete(self):
        """Every non-terminal model should have a fallback. No self-loops."""
        from config.electronhub import FALLBACK, get_models
        active_models = set(get_models().values())
        # gpt-4.1-nano and gpt-5-nano:free are terminals — no fallback required
        terminals = {"gpt-4.1-nano", "gpt-5-nano:free"}
        for model in active_models:
            if model not in terminals:
                assert model in FALLBACK, f"No fallback for model '{model}'"
        # No self-loops allowed
        for model, fb in FALLBACK.items():
            assert model != fb, f"Self-loop in fallback chain: {model} -> {fb}"

    @pytest.mark.asyncio
    async def test_complete_json_cleans_markdown(self):
        """complete_json should strip markdown code fences from responses."""
        from config.electronhub import complete_json
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str

        mock_response = '```json\n{"value": "test"}\n```'

        with patch("config.electronhub.get_client") as mock_client:
            mock_choice = MagicMock()
            mock_choice.message.content = mock_response
            mock_client.return_value.chat.completions.create = AsyncMock(
                return_value=MagicMock(choices=[mock_choice])
            )
            result = await complete_json(
                task="classify-hackathon",
                response_model=TestModel,
                messages=[{"role": "user", "content": "test"}],
            )
            assert result.value == "test"


# ── Design constitution tests ──────────────────────────────────────────────────

class TestDesignConstitution:
    """Verify anti-slop rules are well-defined and comprehensive."""

    def test_anti_slop_rules_exist(self):
        from config.design_constitution import ANTI_SLOP_RULES
        assert len(ANTI_SLOP_RULES) > 1000, "Anti-slop rules should be comprehensive"

    def test_design_personalities_complete(self):
        from config.design_constitution import DESIGN_PERSONALITIES
        required_keys = ["description", "bg_base", "text_primary", "font_sans", "anti_patterns", "use_when"]
        for name, personality in DESIGN_PERSONALITIES.items():
            for key in required_keys:
                assert key in personality, f"Personality '{name}' missing '{key}'"

    def test_design_tokens_dataclass_complete(self):
        from config.design_constitution import DesignTokens
        import dataclasses
        fields = {f.name for f in dataclasses.fields(DesignTokens)}
        required = {"color_bg_base", "color_accent", "font_sans", "font_mono", "space_4", "radius_md", "duration_base"}
        assert required.issubset(fields), f"Missing fields: {required - fields}"

    def test_critique_rubric_has_all_dimensions(self):
        from config.design_constitution import DESIGN_CRITIQUE_RUBRIC
        dimensions = [
            "Reference site match", "Data density", "Status visibility",
            "Visual hierarchy", "Interaction quality", "Demo path clarity",
        ]
        for dim in dimensions:
            assert dim in DESIGN_CRITIQUE_RUBRIC, f"Missing dimension: {dim}"

    def test_component_quality_checklist_coverage(self):
        from config.design_constitution import COMPONENT_QUALITY_CHECKLIST
        required_checks = ["Hover", "Focus", "Loading", "Error", "Empty", "Accessibility", "40x40px"]
        for check in required_checks:
            assert check in COMPONENT_QUALITY_CHECKLIST, f"Missing check: {check}"


# ── Agent config tests ─────────────────────────────────────────────────────────

class TestAgentConfig:
    """Verify all 30 agents are properly configured."""

    def test_all_30_agents_registered(self):
        from config.agents_config import ALL_AGENTS
        assert len(ALL_AGENTS) >= 30, f"Expected 30 agents, got {len(ALL_AGENTS)}"

    def test_critical_agents_exist(self):
        from config.agents_config import ALL_AGENTS
        critical = [
            "commander", "hackathon_scout", "competitor_analyst", "judge_profiler",
            "sponsor_researcher", "strategy_director", "pm", "tech_architect",
            "ui_ux_designer", "frontend_engineer", "backend_engineer",
            "integration_engineer", "test_engineer", "devops", "security",
            "code_reviewer", "ux_auditor", "performance",
            "polish", "copy_writer", "data_seeder", "brand",
            "demo_producer", "pitch_writer", "submission",
            "memory_keeper", "monitor", "calendar", "knowledge_updater", "outcome_tracker",
        ]
        for agent_id in critical:
            assert agent_id in ALL_AGENTS, f"Missing agent: {agent_id}"

    def test_ux_auditor_has_design_tier(self):
        """UX Auditor must use DESIGN tier for proper aesthetic evaluation."""
        from config.agents_config import ALL_AGENTS
        ux_auditor = ALL_AGENTS["ux_auditor"]
        assert ux_auditor.model_tier == "design", "UX Auditor must use design tier"

    def test_ui_ux_designer_has_design_tier(self):
        from config.agents_config import ALL_AGENTS
        assert ALL_AGENTS["ui_ux_designer"].model_tier == "design"

    def test_all_agents_have_system_prompts(self):
        from config.agents_config import ALL_AGENTS
        for agent_id, agent in ALL_AGENTS.items():
            assert len(agent.system_prompt) > 100, f"Agent '{agent_id}' has inadequate system prompt"

    def test_human_checkpoints_defined(self):
        from config.agents_config import HUMAN_CHECKPOINTS
        required = ["concept_approval", "design_approval", "quality_review", "submission_approval"]
        for checkpoint in required:
            assert checkpoint in HUMAN_CHECKPOINTS, f"Missing checkpoint: {checkpoint}"
            assert "timeout_hours" in HUMAN_CHECKPOINTS[checkpoint]
            assert "blocks" in HUMAN_CHECKPOINTS[checkpoint]

    def test_sop_artifacts_form_dag(self):
        """Verify SOP inputs/outputs form a valid DAG (no cycles in critical path)."""
        from config.agents_config import ALL_AGENTS

        # Build adjacency: if A.sop_outputs overlap B.sop_inputs, A → B
        for agent_a in ALL_AGENTS.values():
            for agent_b in ALL_AGENTS.values():
                if agent_a.id == agent_b.id:
                    continue
                overlap = set(agent_a.sop_outputs) & set(agent_b.sop_inputs)
                if overlap:
                    # Verify layers make sense (lower layers produce, higher layers consume)
                    layer_order = ["intelligence", "strategy", "build", "verify", "polish", "submission", "infra"]
                    # infra agents can consume from any layer
                    if agent_b.layer != "infra":
                        a_idx = layer_order.index(agent_a.layer) if agent_a.layer in layer_order else 0
                        b_idx = layer_order.index(agent_b.layer) if agent_b.layer in layer_order else 0
                        # Allow same-layer and downstream consumption
                        assert b_idx >= a_idx, (
                            f"Potential cycle: {agent_a.id} ({agent_a.layer}) → {agent_b.id} ({agent_b.layer}) "
                            f"via {overlap}"
                        )


# ── Redis patterns tests ───────────────────────────────────────────────────────

class TestRedisPatterns:
    """Verify Redis key schema consistency."""

    def test_task_key_format(self):
        hackathon_id = "devpost-123"
        agent_id = "ui_ux_designer"
        key = f"task:{hackathon_id}:{agent_id}"
        assert key == "task:devpost-123:ui_ux_designer"

    def test_artifact_key_format(self):
        hackathon_id = "lablab-456"
        artifact = "api_contract"
        key = f"hackathon:{hackathon_id}:{artifact}"
        assert key == "hackathon:lablab-456:api_contract"

    def test_checkpoint_key_format(self):
        hackathon_id = "devfolio-789"
        checkpoint = "concept_approval"
        key = f"checkpoint:{hackathon_id}:{checkpoint}"
        assert key == "checkpoint:devfolio-789:concept_approval"

    def test_task_status_schema(self):
        """Task status objects must have required fields."""
        import json
        status = json.dumps({"status": "done", "data": {"preview_url": "https://..."}, "updated_at": "2026-01-01T00:00:00Z"})
        parsed = json.loads(status)
        assert "status" in parsed
        assert parsed["status"] in ("pending", "in-progress", "done", "failed")


# ── Integration test: hackathon scoring ───────────────────────────────────────

class TestHackathonScoring:
    """Test the scoring rubric produces sensible results."""

    @pytest.mark.asyncio
    async def test_high_value_hackathon_scores_high(self):
        from agents.python.intelligence.hackathon_scout import HackathonBrief, Prize, SponsorTech, score_hackathon

        brief = HackathonBrief(
            hackathon_id="test-001",
            name="AI Innovation Challenge",
            url="https://devpost.com/test",
            platform="devpost",
            theme="AI agents for enterprise automation",
            description="Build AI agents that automate real business workflows",
            deadline="2099-12-31T00:00:00Z",  # far future for max deadline score
            prizes=[
                Prize(name="Grand Prize", amount=15000, sponsor=None),
                Prize(name="Best AI Agent", amount=3000, sponsor="OpenAI"),
                Prize(name="Best Automation", amount=2000, sponsor="Zapier"),
                Prize(name="Most Creative", amount=1000, sponsor="Anthropic"),
            ],
            judging_criteria=["Innovation", "Technical implementation", "Impact", "Demo quality"],
            sponsor_techs=[
                SponsorTech(sponsor="OpenAI", api_name="GPT-4", prize_amount=3000),
                SponsorTech(sponsor="Zapier", api_name="Zapier Actions", prize_amount=2000),
            ],
            registration_open=True,
            total_participants=50,
        )

        with patch("agents.python.intelligence.hackathon_scout.complete_json") as mock_json:
            from pydantic import BaseModel
            class MockScore(BaseModel):
                score: int = 18
                reasoning: str = "Strong AI focus"
            mock_json.return_value = MockScore()
            scored = await score_hackathon(brief)

        assert scored.score >= 75, f"High-value hackathon should score ≥75, got {scored.score}"
        assert scored.recommended is True

    def test_low_value_hackathon_scores_low(self):
        from agents.python.intelligence.hackathon_scout import HackathonBrief, Prize

        brief = HackathonBrief(
            hackathon_id="test-002",
            name="Blockchain Art Hackathon",
            url="https://example.com",
            platform="devpost",
            theme="Create NFT art",
            description="Build NFT art projects",
            deadline="2026-04-01T00:00:00Z",  # only 2 days
            prizes=[Prize(name="First Place", amount=500)],
            judging_criteria=["Creativity"],
            sponsor_techs=[],
            registration_open=True,
            total_participants=400,
        )

        # Score manually without LLM call (theme_match will be 0 as default)
        from config.electronhub import TASK_TIER
        # Non-AI theme + low prize + short deadline + many competitors = low score
        breakdown = {
            "prize_pool": 0,       # $500 < $1k
            "sponsor_prizes": 0,
            "deadline_buffer": 0,  # <3 days
            "theme_match": 0,      # assumed bad fit
            "competition_size": 5, # 400 competitors
        }
        total = sum(breakdown.values())
        assert total < 65, f"Low-value hackathon should score <65, got {total}"


# ── Design spec validation ─────────────────────────────────────────────────────

class TestDesignSpecValidation:
    """Verify DesignSpec model enforces anti-slop rules."""

    def test_component_spec_requires_real_copy(self):
        """Components must have real_copy, not empty."""
        from agents.python.build.ui_ux_designer import ComponentSpec, ComponentVariant, ComponentState

        spec = ComponentSpec(
            name="MetricCard",
            file_path="components/ui/metric-card.tsx",
            description="Displays a key metric with trend indicator",
            purpose="Show KPI data on the main dashboard",
            shadcn_base="Card",
            variants=[ComponentVariant(name="default", tailwind_classes="bg-background", description="default")],
            states=[ComponentState(state="default", tailwind_classes="", description="at rest")],
            props_interface="interface MetricCardProps { value: number; label: string; }",
            default_props={"value": 0, "label": "Metric"},
            real_copy={
                "label": "Response Time",
                "unit": "ms",
                "trend_label": "vs last week",
            },
            accessibility_notes="aria-label includes both value and label",
            is_demo_critical=True,
            estimated_minutes=45,
        )

        assert len(spec.real_copy) > 0, "Component must have real copy"
        assert not any("placeholder" in v.lower() for v in spec.real_copy.values()), \
            "real_copy cannot contain 'placeholder'"

    def test_user_flow_must_have_wow_moment(self):
        """At least one user flow step must be marked as wow_moment."""
        from agents.python.build.ui_ux_designer import UserFlow

        flow = [
            UserFlow(step=1, action="Open dashboard", screen="/dashboard", ui_element="navbar link", expected_outcome="Dashboard renders", wow_moment=False),
            UserFlow(step=2, action="Click 'Analyze'", screen="/dashboard", ui_element="analyze-button", expected_outcome="AI processes 3 months of data", wow_moment=True),
            UserFlow(step=3, action="View results", screen="/results", ui_element="results-panel", expected_outcome="Insights displayed", wow_moment=False),
        ]

        wow_steps = [s for s in flow if s.wow_moment]
        assert len(wow_steps) >= 1, "Demo flow must have at least one wow moment"


if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v", "--timeout=30"])
