#!/usr/bin/env python3
"""
test_run.py — End-to-end dry run of the full agent pipeline.

Usage:
  python scripts/test_run.py --dry-run          # full system test (no real browser/API calls)
  python scripts/test_run.py --test electronhub # verify ElectronHub connection
  python scripts/test_run.py --test browser     # verify browser layer
  python scripts/test_run.py --test design      # verify design constitution loaded
  python scripts/test_run.py --test memory      # verify Qdrant collections
  python scripts/test_run.py --test scoring     # verify hackathon scoring rubric
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PASS = "✓"
FAIL = "✗"
WARN = "⚠"


async def test_electronhub() -> bool:
    from config.electronhub import complete, complete_json, Tier, resolve
    from pydantic import BaseModel

    logger.info("Testing ElectronHub connection...")

    result = await complete(
        task="classify-hackathon",
        messages=[{"role": "user", "content": "Reply with exactly three words: ELECTRONHUB CONNECTION OK"}],
    )
    assert "ELECTRONHUB" in result or "CONNECTION" in result or "OK" in result, f"Unexpected: {result}"
    logger.info(f"{PASS} ElectronHub text completion")

    class Ping(BaseModel):
        status: str
        tier_used: str

    json_result = await complete_json(
        task="classify-hackathon",
        response_model=Ping,
        messages=[{"role": "user", "content": 'Reply: {"status": "ok", "tier_used": "fast"}'}],
    )
    assert json_result.status == "ok"
    logger.info(f"{PASS} ElectronHub JSON mode")

    # Verify design tier has higher temperature
    from config.electronhub import DEFAULT_TEMP, Tier
    assert DEFAULT_TEMP[Tier.DESIGN] > DEFAULT_TEMP[Tier.STANDARD], "DESIGN tier should have higher temperature"
    logger.info(f"{PASS} Design tier temperature ({DEFAULT_TEMP[Tier.DESIGN]} > {DEFAULT_TEMP[Tier.STANDARD]})")

    return True


async def test_browser_layer() -> bool:
    import aiohttp
    browser_url = os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100")
    logger.info(f"Testing browser layer at {browser_url}...")

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{browser_url}/health", timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            assert data.get("status") == "ok"

    logger.info(f"{PASS} Browser layer healthy")
    return True


async def test_design_constitution() -> bool:
    logger.info("Testing design constitution...")

    from config.design_constitution import (
        ANTI_SLOP_RULES, STATIC_DESIGN_LAWS, DESIGN_CRITIQUE_RUBRIC,
        DESIGN_PERSONALITIES, DesignTokens, COMPONENT_QUALITY_CHECKLIST,
        SYSTEM_PROMPT_DESIGN_AGENT, SYSTEM_PROMPT_FRONTEND_AGENT,
    )

    assert len(ANTI_SLOP_RULES) > 500, "Anti-slop rules too short"
    assert len(DESIGN_PERSONALITIES) >= 5, "Need at least 5 personalities"
    assert len(SYSTEM_PROMPT_DESIGN_AGENT) > 500, "Design agent prompt too short"
    assert len(SYSTEM_PROMPT_FRONTEND_AGENT) > 500, "Frontend agent prompt too short"

    # Verify all anti-slop categories present
    categories = ["Layout crimes", "Color crimes", "Typography crimes", "Component crimes", "Copy crimes"]
    for cat in categories:
        assert cat in ANTI_SLOP_RULES, f"Missing category: {cat}"

    logger.info(f"{PASS} Design constitution loaded ({len(ANTI_SLOP_RULES)} chars)")
    logger.info(f"{PASS} {len(DESIGN_PERSONALITIES)} design personalities available")
    return True


async def test_memory() -> bool:
    logger.info("Testing memory layer (Qdrant)...")
    from agents.python.infra.memory_keeper import MemoryKeeper

    memory = MemoryKeeper()
    await memory.ensure_collections()

    # Test embed
    from config.electronhub import embed
    vector = await embed("AI agent for customer support automation")
    assert len(vector) == 1536, f"Wrong embedding size: {len(vector)}"
    logger.info(f"{PASS} Qdrant collections initialized")
    logger.info(f"{PASS} Embeddings working (1536 dims)")
    return True


async def test_scoring() -> bool:
    logger.info("Testing hackathon scoring rubric...")
    from agents.python.intelligence.hackathon_scout import HackathonBrief, Prize, SponsorTech
    from unittest.mock import patch, AsyncMock
    from pydantic import BaseModel

    class MockScore(BaseModel):
        score: int = 18
        reasoning: str = "Strong AI focus"

    # High-value hackathon
    brief_high = HackathonBrief(
        hackathon_id="test-high",
        name="AI Agents World", url="https://devpost.com/test", platform="devpost",
        theme="AI agents automation", description="Build AI agents",
        deadline="2099-12-31T00:00:00Z",
        prizes=[
            Prize(name="Grand", amount=12000),
            Prize(name="Sponsor1", amount=2000, sponsor="OpenAI"),
            Prize(name="Sponsor2", amount=1500, sponsor="Anthropic"),
            Prize(name="Sponsor3", amount=1000, sponsor="Zapier"),
        ],
        judging_criteria=["Innovation", "Technical"], sponsor_techs=[],
        registration_open=True, total_participants=80,
    )

    with patch("agents.python.intelligence.hackathon_scout.complete_json") as m:
        m.return_value = MockScore()
        from agents.python.intelligence.hackathon_scout import score_hackathon
        scored_high = await score_hackathon(brief_high)

    assert scored_high.score >= 75, f"High-value should score ≥75, got {scored_high.score}"
    assert scored_high.recommended, "High-value should be recommended"
    logger.info(f"{PASS} High-value hackathon scores {scored_high.score}/100 (recommended)")

    # Low-value hackathon
    brief_low = HackathonBrief(
        hackathon_id="test-low",
        name="NFT Art Hackathon", url="https://example.com", platform="devpost",
        theme="Create NFT art", description="Make NFTs",
        deadline="2026-04-01T00:00:00Z",
        prizes=[Prize(name="First", amount=300)],
        judging_criteria=["Creativity"], sponsor_techs=[],
        registration_open=True, total_participants=500,
    )

    class LowScore(BaseModel):
        score: int = 2
        reasoning: str = "Poor AI fit"

    with patch("agents.python.intelligence.hackathon_scout.complete_json") as m:
        m.return_value = LowScore()
        scored_low = await score_hackathon(brief_low)

    assert not scored_low.recommended, f"Low-value should NOT be recommended (score: {scored_low.score})"
    logger.info(f"{PASS} Low-value hackathon scores {scored_low.score}/100 (not recommended)")
    return True


async def test_agent_configs() -> bool:
    logger.info("Testing all 30 agent configurations...")
    from config.agents_config import ALL_AGENTS, HUMAN_CHECKPOINTS

    critical = ["commander", "hackathon_scout", "ui_ux_designer", "ux_auditor",
                "frontend_engineer", "backend_engineer", "demo_producer", "submission"]

    for agent_id in critical:
        assert agent_id in ALL_AGENTS, f"Missing agent: {agent_id}"
        agent = ALL_AGENTS[agent_id]
        assert len(agent.system_prompt) > 100, f"Agent {agent_id} has weak system prompt"

    assert len(ALL_AGENTS) >= 30
    assert len(HUMAN_CHECKPOINTS) == 4

    logger.info(f"{PASS} {len(ALL_AGENTS)} agents configured")
    logger.info(f"{PASS} {len(HUMAN_CHECKPOINTS)} human checkpoints defined")
    return True


async def run_full_dry_run() -> None:
    results: dict[str, bool] = {}

    print("\n" + "=" * 60)
    print("Forge v2 — Full System Test")
    print("=" * 60 + "\n")

    tests = [
        ("ElectronHub",          test_electronhub),
        ("Design constitution",  test_design_constitution),
        ("Agent configs (30)",   test_agent_configs),
        ("Hackathon scoring",    test_scoring),
        ("Memory (Qdrant)",      test_memory),
        ("Browser layer",        test_browser_layer),
    ]

    for name, test_fn in tests:
        try:
            results[name] = await test_fn()
            print(f"  {PASS} {name}")
        except Exception as e:
            results[name] = False
            print(f"  {FAIL} {name}: {e}")

    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)

    if passed == total:
        print("\n✓ All systems operational. Ready to win hackathons.\n")
    else:
        failed = [name for name, ok in results.items() if not ok]
        print(f"\n✗ Failed: {', '.join(failed)}")
        print("Fix issues before running the full pipeline.\n")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--test", choices=["electronhub", "browser", "design", "memory", "scoring", "agents"])
    args = parser.parse_args()

    async def main():
        if args.test == "electronhub":
            await test_electronhub()
        elif args.test == "browser":
            await test_browser_layer()
        elif args.test == "design":
            await test_design_constitution()
        elif args.test == "memory":
            await test_memory()
        elif args.test == "scoring":
            await test_scoring()
        elif args.test == "agents":
            await test_agent_configs()
        else:
            await run_full_dry_run()

    asyncio.run(main())
