# -*- coding: utf-8 -*-
"""
forge_tools.py — Claude Code-inspired tool protocol for Forge agents
=====================================================================

Adapted from nirholas/claude-code leaked source (2026-03-31):
  src/Tool.ts         — tool definition pattern with schema, permissions, concurrency
  src/tools/          — self-contained tool modules
  src/cost-tracker.ts — per-turn token cost tracking
  src/tasks/          — background task management
  src/memdir/         — persistent memory directory

Key patterns adopted:
  1. Tool concurrency safety declaration (isConcurrencySafe)
  2. Read-only flagging (isReadOnly)
  3. Plan mode — show actions before executing (EnterPlanModeTool pattern)
  4. Per-agent token budget tracking (cost-tracker.ts)
  5. Structured PATCH protocol for file edits (FileEditTool string-replacement)
  6. Sub-agent spawning with typed results (AgentTool)
  7. Permission rule patterns with wildcards (Bash(git *), FileEdit(src/*))
  8. Memdir-style persistent agent notes (cross-session learning files)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────────────
# TOOL DEFINITION PATTERN
# Adapted from Claude Code's buildTool() pattern in src/Tool.ts
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ForgeTool:
    """
    Self-contained tool definition.

    Adapted from Claude Code's tool pattern:
      - name:               unique tool identifier
      - is_concurrency_safe: can run in parallel with other tools
      - is_read_only:        no side effects — always safe to parallelize
      - permission_pattern:  wildcard rule for auto-approval
      - execute:            async callable that does the work
    """
    name: str
    description: str
    is_concurrency_safe: bool = True
    is_read_only: bool = False
    permission_pattern: str | None = None  # e.g. "Bash(git *)", "FileRead(*)"

    # The actual implementation — injected at creation time
    _execute: Callable | None = field(default=None, repr=False)

    async def execute(self, **kwargs) -> Any:
        if self._execute is None:
            raise NotImplementedError(f"Tool {self.name} has no execute implementation")
        return await self._execute(**kwargs)

    def can_auto_approve(self, input_summary: str) -> bool:
        """Check if this tool call matches a pre-approved permission rule."""
        if self.is_read_only:
            return True
        if self.permission_pattern is None:
            return False
        pattern = self.permission_pattern.replace("*", ".*")
        return bool(re.match(pattern, input_summary))


# ─────────────────────────────────────────────────────────────────────────────
# CONCURRENCY GRAPH
# Adapted from Claude Code's isConcurrencySafe() declarations
# Forge uses this to build the correct parallel execution order
# ─────────────────────────────────────────────────────────────────────────────

# Maps agent_id → list of agent_ids it must wait for before starting
# Derived from is_concurrency_safe=False declarations in AgentDef
AGENT_DEPENDENCIES: dict[str, list[str]] = {
    # Build layer — partial ordering
    "frontend_engineer":    ["tech_architect"],          # needs ApiContract first
    "test_engineer":        ["frontend_engineer", "backend_engineer"],
    "security":             ["frontend_engineer", "backend_engineer"],
    "integration_engineer": ["tech_architect", "backend_engineer"],
    "devops":               ["frontend_engineer", "backend_engineer"],

    # Verify layer — must run after build
    "code_reviewer":        ["frontend_engineer", "backend_engineer"],
    "ux_auditor":           ["frontend_engineer"],        # needs live preview URL
    "performance":          ["frontend_engineer"],        # needs live preview URL

    # Submission — strict ordering
    "demo_producer":        ["polish", "data_seeder"],
    "pitch_writer":         ["polish", "copy_writer"],
    "submission":           ["demo_producer", "pitch_writer"],

    # Outcome tracker — after submission only
    "outcome_tracker":      ["submission"],
}


def get_runnable_now(
    completed: set[str],
    in_progress: set[str],
    all_targets: list[str],
) -> list[str]:
    """
    Return agents that can start RIGHT NOW given what's completed and running.
    Implements the concurrency safety graph from AGENT_DEPENDENCIES.

    Adapted from Claude Code's parallel task scheduling in src/tasks/.
    """
    runnable = []
    for agent_id in all_targets:
        if agent_id in completed or agent_id in in_progress:
            continue
        deps = AGENT_DEPENDENCIES.get(agent_id, [])
        if all(dep in completed for dep in deps):
            runnable.append(agent_id)
    return runnable


# ─────────────────────────────────────────────────────────────────────────────
# PLAN MODE
# Adapted from Claude Code's EnterPlanModeTool / ExitPlanModeTool pattern
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentPlan:
    """
    An agent's intended actions before execution.
    Adapted from Claude Code's plan mode — show intent, get approval, then execute.
    """
    agent_id: str
    hackathon_id: str
    planned_actions: list[str]
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    external_calls: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    risk_level: str = "low"  # low | medium | high


async def request_plan_approval(
    redis: Redis,
    plan: AgentPlan,
    timeout_sec: int = 300,
) -> bool:
    """
    Store plan in Redis and wait for human approval.
    Times out and proceeds (non-blocking) for low-risk plans.
    High-risk plans block until approved.
    """
    key = f"plan_approval:{plan.hackathon_id}:{plan.agent_id}"
    await redis.set(key, json.dumps({
        "agent_id": plan.agent_id,
        "planned_actions": plan.planned_actions,
        "files_to_modify": plan.files_to_modify,
        "files_to_create": plan.files_to_create,
        "external_calls": plan.external_calls,
        "risk_level": plan.risk_level,
        "status": "pending",
    }), ex=3600)

    if plan.risk_level == "low":
        # Auto-approve low-risk plans after a brief display window
        logger.info(f"[forge:plan] Auto-approving low-risk plan for {plan.agent_id}: {plan.planned_actions}")
        return True

    # Wait for human approval (high/medium risk)
    start = time.time()
    while time.time() - start < timeout_sec:
        raw = await redis.get(key)
        if raw:
            data = json.loads(raw)
            if data.get("approved"):
                return True
            if data.get("rejected"):
                return False
        await asyncio.sleep(10)

    # Timeout: proceed with caution for medium, block for high
    if plan.risk_level == "medium":
        logger.warning(f"[forge:plan] Plan approval timed out for {plan.agent_id} — proceeding (medium risk)")
        return True

    logger.error(f"[forge:plan] Plan approval timed out for {plan.agent_id} — BLOCKING (high risk)")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# COST TRACKER
# Adapted from Claude Code's cost-tracker.ts
# ─────────────────────────────────────────────────────────────────────────────

# Token costs in USD per 1M tokens (ElectronHub pricing)
# Pricing per million tokens (input/output) — updated 2026-03-31
# Source: https://api.electronhub.ai/v1/models + Anthropic pricing page
TOKEN_COSTS: dict[str, dict[str, float]] = {
    # Anthropic (current SOTA)
    "claude-opus-4-6":    {"input": 5.0,   "output": 25.0},
    "claude-sonnet-4-6":  {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5":   {"input": 0.25,  "output": 1.25},
    # Anthropic (legacy — kept for users on older model names)
    "claude-opus-4-5":    {"input": 5.0,   "output": 25.0},
    "claude-sonnet-4-5":  {"input": 3.0,   "output": 15.0},
    # OpenAI (current SOTA)
    "gpt-4.1":            {"input": 2.0,   "output": 8.0},
    "gpt-4.1-mini":       {"input": 0.4,   "output": 1.6},
    "gpt-4.1-nano":       {"input": 0.1,   "output": 0.4},
    "gpt-5-nano":         {"input": 0.05,  "output": 0.4},
    "gpt-5-nano:free":    {"input": 0.0,   "output": 0.0},
    # OpenAI (legacy)
    "gpt-4o":             {"input": 2.5,   "output": 10.0},
    "gpt-4o-mini":        {"input": 0.15,  "output": 0.6},
    # Google (if user overrides to Gemini)
    "gemini-2.5-pro":     {"input": 2.0,   "output": 12.0},
    "gemini-2.0-flash":   {"input": 0.075, "output": 0.3},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost for a single LLM call."""
    rates = TOKEN_COSTS.get(model, {"input": 3.0, "output": 15.0})
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


async def track_agent_cost(
    redis: Redis,
    hackathon_id: str,
    agent_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> dict:
    """
    Record token usage and cost for one agent call.
    Adapted from Claude Code's cost-tracker.ts per-turn tracking.

    Usage:
        from config.electronhub import complete
        # After every LLM call, track it:
        await track_agent_cost(redis, hackathon_id, "ui_ux_designer",
                               "claude-sonnet-4-5", 2400, 800)
    """
    cost = estimate_cost_usd(model, input_tokens, output_tokens)
    key = f"cost:{hackathon_id}:{agent_id}"

    raw = await redis.get(key)
    existing = json.loads(raw) if raw else {
        "agent_id": agent_id,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "calls": 0,
    }

    existing["total_input_tokens"]  += input_tokens
    existing["total_output_tokens"] += output_tokens
    existing["total_cost_usd"]      += cost
    existing["calls"]               += 1

    await redis.set(key, json.dumps(existing), ex=604800)
    return existing


async def get_run_cost_summary(redis: Redis, hackathon_id: str) -> dict:
    """Get total cost breakdown for a hackathon run."""
    keys = await redis.keys(f"cost:{hackathon_id}:*")
    summary = {"total_usd": 0.0, "by_agent": {}, "total_tokens": 0}

    for key in keys:
        raw = await redis.get(key)
        if raw:
            data = json.loads(raw)
            agent_id = data["agent_id"]
            summary["by_agent"][agent_id] = {
                "cost_usd": round(data["total_cost_usd"], 4),
                "tokens": data["total_input_tokens"] + data["total_output_tokens"],
                "calls": data["calls"],
            }
            summary["total_usd"]    += data["total_cost_usd"]
            summary["total_tokens"] += data["total_input_tokens"] + data["total_output_tokens"]

    summary["total_usd"] = round(summary["total_usd"], 4)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# MEMDIR — PERSISTENT AGENT NOTES
# Adapted from Claude Code's src/memdir/ pattern
# Cross-session file-based notes that complement Mem0/Qdrant
# ─────────────────────────────────────────────────────────────────────────────

MEMDIR_PATH = Path(os.environ.get("FORGE_MEMDIR", "/var/forge/memdir"))


def get_agent_memdir(agent_id: str) -> Path:
    """Get the persistent memory directory for an agent."""
    d = MEMDIR_PATH / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_agent_note(agent_id: str, note_name: str, content: str) -> Path:
    """
    Write a persistent note for an agent.
    Adapted from Claude Code's memdir pattern — agents write learned facts
    to files that persist across sessions and are injected into future prompts.

    Example:
        write_agent_note("strategy_director", "winning_patterns_2026.md",
                        "Supply chain agents win on Devpost. Chatbots lose.")
    """
    path = get_agent_memdir(agent_id) / f"{note_name}.md"
    path.write_text(content, encoding="utf-8")
    logger.info(f"[forge:memdir] {agent_id} wrote note: {note_name}")
    return path


def read_agent_notes(agent_id: str) -> dict[str, str]:
    """Read all persistent notes for an agent — injected into system prompt."""
    memdir = get_agent_memdir(agent_id)
    notes = {}
    for f in sorted(memdir.glob("*.md")):
        notes[f.stem] = f.read_text(encoding="utf-8")
    return notes


def build_memdir_context(agent_id: str) -> str:
    """
    Build a memdir context block to inject into an agent's system prompt.
    Adapted from Claude Code's /memory command and memdir injection.
    """
    notes = read_agent_notes(agent_id)
    if not notes:
        return ""

    lines = ["## Persistent memory (from past runs)\n"]
    for name, content in notes.items():
        lines.append(f"### {name.replace('_', ' ').title()}\n{content}\n")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PATCH PROTOCOL
# Standardized FIND/REPLACE file editing — from Claude Code's FileEditTool
# ─────────────────────────────────────────────────────────────────────────────

PATCH_PATTERN = re.compile(
    r"PATCH:\s*(.+?)\nFIND:\s*(.*?)\nREPLACE:\s*(.*?)\nEND",
    re.DOTALL,
)


def parse_patches(text: str) -> list[dict]:
    """
    Parse PATCH blocks from LLM output.
    Format (from Claude Code's FileEditTool string-replacement protocol):

        PATCH: path/to/file.tsx
        FIND: exact string to find
        REPLACE: exact string to replace with
        END

    Returns list of {file, find, replace} dicts.
    """
    patches = []
    for m in PATCH_PATTERN.finditer(text):
        patches.append({
            "file": m.group(1).strip(),
            "find": m.group(2).strip(),
            "replace": m.group(3).strip(),
        })
    return patches


def apply_patches(patches: list[dict], root_dir: Path) -> tuple[list[str], list[str]]:
    """
    Apply a list of PATCH blocks to files under root_dir.
    Returns (applied_files, failed_files).

    This is the production-grade version of the pattern already used in polish_agents.py,
    now centralized so all agents can use the same reliable patch application.
    """
    applied, failed = [], []

    for patch in patches:
        target = root_dir / patch["file"]

        if not target.exists():
            failed.append(f"{patch['file']}: file not found")
            continue

        try:
            content = target.read_text(encoding="utf-8")
            if patch["find"] not in content:
                failed.append(f"{patch['file']}: FIND string not found")
                continue
            target.write_text(content.replace(patch["find"], patch["replace"], 1))
            applied.append(patch["file"])
        except Exception as e:
            failed.append(f"{patch['file']}: {e}")

    return applied, failed


# ─────────────────────────────────────────────────────────────────────────────
# SUB-AGENT SPAWNER
# Adapted from Claude Code's AgentTool — spawn child agents dynamically
# ─────────────────────────────────────────────────────────────────────────────

async def spawn_sub_agent(
    redis: Redis,
    parent_agent_id: str,
    hackathon_id: str,
    task_description: str,
    input_data: dict,
    model_tier: str = "standard",
    timeout_sec: int = 3600,
) -> dict | None:
    """
    Dynamically spawn a named sub-agent for a specific task.
    Adapted from Claude Code's AgentTool pattern — any agent can create child agents.

    The sub-agent runs as a one-shot ElectronHub call with its own task description
    and returns structured output. Parent waits for result.

    Usage:
        # From inside the Strategy Director, spawn a sub-agent to research one sponsor:
        result = await spawn_sub_agent(
            redis, "strategy_director", hackathon_id,
            "Research Stripe's hackathon prize requirements and API complexity",
            {"sponsor": "Stripe", "prize_amount": 3000},
        )
    """
    from config.electronhub import complete_json
    from pydantic import BaseModel

    class SubAgentResult(BaseModel):
        success: bool
        output: dict
        summary: str

    sub_id = f"{parent_agent_id}_sub_{int(asyncio.get_event_loop().time())}"
    logger.info(f"[forge:agent] {parent_agent_id} spawning sub-agent: {sub_id}")

    # Track the sub-agent in Redis
    await redis.set(
        f"task:{hackathon_id}:{sub_id}",
        json.dumps({"status": "in-progress", "parent": parent_agent_id}),
        ex=timeout_sec + 600,
    )

    try:
        result = await complete_json(
            task="analyze-competitors",  # reuse existing tier
            response_model=SubAgentResult,
            messages=[{
                "role": "user",
                "content": f"""You are a specialist sub-agent spawned by {parent_agent_id}.

Task: {task_description}

Input data:
{json.dumps(input_data, indent=2)}

Complete the task and return structured output with:
- success: true/false
- output: the result data as a dict
- summary: one sentence describing what you did and what you found""",
            }],
        )
        await redis.set(
            f"task:{hackathon_id}:{sub_id}",
            json.dumps({"status": "done", "data": result.model_dump()}),
            ex=604800,
        )
        return result.model_dump()

    except Exception as e:
        logger.error(f"[forge:agent] Sub-agent {sub_id} failed: {e}")
        await redis.set(
            f"task:{hackathon_id}:{sub_id}",
            json.dumps({"status": "failed", "error": str(e)}),
            ex=604800,
        )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PERMISSION RULES
# Adapted from Claude Code's permission rule system
# Wildcard patterns that pre-approve specific tool invocations
# ─────────────────────────────────────────────────────────────────────────────

# Default permission rules for each agent
# Format: "TOOL(glob_pattern)" — adapted from Claude Code's permission rule syntax
DEFAULT_PERMISSION_RULES: dict[str, list[str]] = {
    "hackathon_scout":       ["WebFetch(*)", "WebSearch(*)", "BrowserScrape(*)"],
    "competitor_analyst":    ["WebFetch(*)", "WebSearch(*)"],
    "judge_profiler":        ["WebFetch(*)", "WebSearch(*)"],
    "sponsor_researcher":    ["WebFetch(*)", "WebSearch(*)"],
    "strategy_director":     ["MemoryRead(*)", "WebSearch(*)"],
    "pm":                    ["MemoryRead(*)", "FileRead(*)"],
    "tech_architect":        ["FileRead(*)", "FileWrite(/tmp/*)"],
    "ui_ux_designer":        ["FileWrite(/tmp/*)", "FigmaWrite(*)", "StitchCall(*)"],
    "frontend_engineer":     ["Bash(npm *)", "Bash(npx *)", "FileWrite(*)", "FileRead(*)"],
    "backend_engineer":      ["Bash(pip *)", "Bash(alembic *)", "FileWrite(*)", "FileRead(*)"],
    "integration_engineer":  ["FileWrite(integrations/*)", "WebFetch(*/docs*)"],
    "test_engineer":         ["FileWrite(tests/*)", "Bash(pytest *)", "Bash(npx playwright *)"],
    "devops":                ["FileWrite(.github/*)", "Bash(git *)"],
    "security":              ["Bash(npm audit)", "Bash(pip-audit)", "FileRead(*)"],
    "code_reviewer":         ["FileRead(*)", "Bash(tsc --noEmit)", "Bash(eslint *)"],
    "ux_auditor":            ["BrowserScreenshot(*)", "BrowserLighthouse(*)"],
    "performance":           ["BrowserLighthouse(*)", "BrowserScreenshot(*)"],
    "polish":                ["FileRead(*)", "FileWrite(src/*)"],
    "copy_writer":           ["FileRead(*)", "FileWrite(src/*)"],
    "data_seeder":           ["FileWrite(tests/*)", "FileWrite(scripts/*)"],
    "brand":                 ["FileWrite(public/*)", "FileRead(*)"],
    "demo_producer":         ["Bash(ffmpeg *)", "BrowserRecordDemo(*)", "ElevenLabsCall(*)"],
    "pitch_writer":          ["FileWrite(docs/*)", "WebFetch(*)"],
    "submission":            ["BrowserSubmit(*)", "WebFetch(*)"],
    "memory_keeper":         ["QdrantWrite(*)", "Mem0Write(*)"],
    "monitor":               ["RedisRead(*)", "DiscordAlert(*)"],
    "calendar":              ["GoogleCalendarWrite(*)", "N8NWebhook(*)"],
    "knowledge_updater":     ["FileWrite(config/design_constitution.py)", "WebSearch(*)"],
    "outcome_tracker":       ["WebFetch(*)", "Mem0Write(*)", "QdrantWrite(*)", "RedisWrite(*)"],
}


def check_permission(agent_id: str, tool_call: str) -> bool:
    """
    Check if an agent has pre-approved permission for a tool call.
    Adapted from Claude Code's permission checking in src/hooks/toolPermission/.

    Returns True if auto-approved, False if human prompt required.
    """
    rules = DEFAULT_PERMISSION_RULES.get(agent_id, [])
    for rule in rules:
        # Parse "TOOL(pattern)" format
        m = re.match(r"(\w+)\((.+)\)", rule)
        if not m:
            continue
        tool_name, pattern = m.group(1), m.group(2)
        regex = pattern.replace("*", ".*").replace("?", ".")
        if tool_call.startswith(tool_name + "(") and re.search(regex, tool_call):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# CRON TRIGGER SYSTEM
# Adapted from Claude Code's ScheduleCronTool / CronCreateTool
# ─────────────────────────────────────────────────────────────────────────────

async def schedule_cron_trigger(
    redis: Redis,
    trigger_name: str,
    agent_id: str,
    hackathon_id: str,
    run_at_iso: str,
    input_data: dict,
    repeat_every_hours: int | None = None,
) -> str:
    """
    Schedule an agent trigger to fire at a specific time.
    Adapted from Claude Code's ScheduleCronTool — any agent can schedule future work.

    Used by:
        - Calendar Agent: schedule 5 events per hackathon
        - Outcome Tracker: schedule self to retry in 6h if results not posted
        - Monitor: schedule daily health reports

    The Temporal worker picks these up and fires them at the right time.
    """
    trigger_id = f"cron:{trigger_name}:{hackathon_id}"
    payload = {
        "trigger_id": trigger_id,
        "agent_id": agent_id,
        "hackathon_id": hackathon_id,
        "run_at": run_at_iso,
        "input_data": input_data,
        "repeat_every_hours": repeat_every_hours,
        "created_at": asyncio.get_event_loop().time(),
    }
    await redis.set(trigger_id, json.dumps(payload), ex=86400 * 30)
    await redis.zadd("forge:cron_queue", {trigger_id: 0})  # sorted set for ordering
    logger.info(f"[forge:cron] Scheduled {agent_id} trigger '{trigger_name}' at {run_at_iso}")
    return trigger_id


async def check_due_cron_triggers(redis: Redis) -> list[dict]:
    """
    Check for cron triggers that are due to fire.
    Called by Monitor agent every 60 seconds.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    due = []

    trigger_ids = await redis.zrange("forge:cron_queue", 0, -1)
    for tid in trigger_ids:
        raw = await redis.get(tid)
        if not raw:
            await redis.zrem("forge:cron_queue", tid)
            continue
        data = json.loads(raw)
        if data["run_at"] <= now_iso:
            due.append(data)
            if data.get("repeat_every_hours"):
                # Reschedule
                from datetime import timedelta
                next_run = (datetime.fromisoformat(data["run_at"])
                            + timedelta(hours=data["repeat_every_hours"])).isoformat()
                data["run_at"] = next_run
                await redis.set(tid, json.dumps(data), ex=86400 * 30)
            else:
                await redis.delete(tid)
                await redis.zrem("forge:cron_queue", tid)

    return due


# ─────────────────────────────────────────────────────────────────────────────
# MCP CLIENT FOR SPONSOR APIs
# Feature 7: Adapted from Claude Code's src/services/mcp/
# Agents call sponsor MCP servers directly instead of generating brittle code
# ─────────────────────────────────────────────────────────────────────────────

# Known MCP server URLs for major hackathon sponsors
# Integration Engineer checks this before falling back to code generation
SPONSOR_MCP_URLS: dict[str, str] = {
    "stripe":   "https://mcp.stripe.com",
    "notion":   "https://mcp.notion.com",
    "linear":   "https://mcp.linear.app",
    "github":   "https://api.githubcopilot.com/mcp",
    "zapier":   "https://mcp.zapier.com",
    "vercel":   "https://mcp.vercel.com",
    "supabase": "https://mcp.supabase.com",
    "neon":     "https://mcp.neon.tech",
}


async def call_mcp_tool(
    server_name: str,
    tool_name: str,
    arguments: dict,
    api_key: str | None = None,
    server_url: str | None = None,
) -> dict:
    """
    Call a tool on an MCP server.
    Adapted from Claude Code's MCPTool pattern.

    Integration Engineer uses this when a sponsor has a known MCP server
    instead of generating an HTTP client from scratch.

    Returns the tool result dict or raises on error.

    Example:
        result = await call_mcp_tool(
            "stripe", "create_payment_intent",
            {"amount": 1000, "currency": "usd"},
            api_key=os.environ["STRIPE_API_KEY"]
        )
    """
    import aiohttp as _aio

    url = server_url or SPONSOR_MCP_URLS.get(server_name.lower())
    if not url:
        raise ValueError(f"No MCP server URL known for sponsor '{server_name}'. "
                         f"Known sponsors: {list(SPONSOR_MCP_URLS.keys())}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    async with _aio.ClientSession() as session:
        async with session.post(
            f"{url.rstrip('/')}/mcp",
            json=payload,
            headers=headers,
            timeout=_aio.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"MCP server {server_name} returned {resp.status}: {text[:200]}")
            data = await resp.json()

    if "error" in data:
        raise RuntimeError(f"MCP tool error from {server_name}/{tool_name}: {data['error']}")

    return data.get("result", data)


async def list_mcp_tools(
    server_name: str,
    api_key: str | None = None,
    server_url: str | None = None,
) -> list[dict]:
    """
    Enumerate available tools on an MCP server.
    Integration Engineer calls this to discover what a sponsor exposes
    before deciding how to integrate.
    """
    import aiohttp as _aio

    url = server_url or SPONSOR_MCP_URLS.get(server_name.lower())
    if not url:
        return []

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    try:
        async with _aio.ClientSession() as session:
            async with session.post(
                f"{url.rstrip('/')}/mcp",
                json=payload,
                headers=headers,
                timeout=_aio.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("result", {}).get("tools", [])
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE FLAGS
# Feature 8: Adapted from Claude Code's bun:bundle feature() pattern
# Runtime env-var-based flags — no build-time stripping needed in Python
# ─────────────────────────────────────────────────────────────────────────────

def feature(flag: str) -> bool:
    """
    Check if a Forge feature flag is enabled.
    Adapted from Claude Code's feature() pattern.

    Flags are set via FORGE_FLAGS env var (comma-separated) or
    individual FORGE_FLAG_{FLAG_NAME}=1 env vars.

    Usage:
        if feature("SKIP_SECURITY_SCAN"):
            logger.info("Security scan disabled by feature flag")
            return SecurityReport(passed=True, ...)

        if feature("FIGMA_AGENT"):
            await trigger_agent(redis, hackathon_id, "figma_agent", {...})

    Example .env:
        FORGE_FLAGS=SKIP_SECURITY_SCAN,FAST_BUILD_MODE
        # or individually:
        FORGE_FLAG_SKIP_SECURITY_SCAN=1
    """
    flag_upper = flag.upper()

    # Check individual env var first (FORGE_FLAG_SKIP_SECURITY_SCAN=1)
    individual = os.environ.get(f"FORGE_FLAG_{flag_upper}", "").strip()
    if individual in ("1", "true", "yes", "on"):
        return True

    # Check comma-separated FORGE_FLAGS list
    flags_raw = os.environ.get("FORGE_FLAGS", "").strip()
    if flags_raw:
        flags = {f.strip().upper() for f in flags_raw.split(",")}
        return flag_upper in flags

    return False
