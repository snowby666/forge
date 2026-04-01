#!/usr/bin/env python3
# Windows users: run as  python forge <command>
#                or use  forge.cmd <command>
"""
forge — the CLI entrypoint for the Forge autonomous hackathon swarm.

Usage:
  forge scout              Discover and score this week's hackathons
  forge run [--id ID]      Full autonomous build cycle
  forge status [--id ID]   Live view of all agent statuses
  forge approve            Human checkpoint interface
  forge plan [--id ID]     Show build plan (tasks, critical path, risks)
  forge knowledge          Update design + strategy intelligence
  forge test               Run system health checks
  forge ls                 List all active hackathons
  forge web                Start web dashboard (remote approval from any device)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.redis_client import get_redis
from dotenv import load_dotenv
load_dotenv()
# Also load forge.secrets (env vars take precedence)
_secrets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forge.secrets")
if os.path.exists(_secrets):
    load_dotenv(_secrets, override=False)

# ── ANSI colors ───────────────────────────────────────────────────────────────

BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
PURPLE = "\033[35m"
RESET  = "\033[0m"

def header():
    print(f"""
{BOLD}{CYAN}
  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
{RESET}{DIM}  30 agents. One submission. Every time.{RESET}
""")

def ok(msg: str):    print(f"  {GREEN}✓{RESET} {msg}")
def warn(msg: str):  print(f"  {YELLOW}⚠{RESET} {msg}")
def err(msg: str):   print(f"  {RED}✗{RESET} {msg}")
def info(msg: str):  print(f"  {CYAN}→{RESET} {msg}")
def section(title: str): print(f"\n{BOLD}{title}{RESET}")


# ── Commands ──────────────────────────────────────────────────────────────────

def _print_hackathon_detail(h, verbose: bool = True):
    """Print detailed hackathon intel."""
    prize_total = sum(p.amount or 0 for p in h.prizes)
    bd = h.score_breakdown or {}
    qualifies = h.score >= 65
    marker = f"{GREEN}✓ qualifies{RESET}" if qualifies else f"{DIM}below threshold{RESET}"
    deep_marker = f" {CYAN}[deep]{RESET}" if h.deep_scraped else ""

    # Build modifier tags
    raw = h._raw_listing if hasattr(h, '_raw_listing') else {}
    tags = []
    if raw.get("featured"):
        tags.append(f"{GREEN}★ FEATURED{RESET}")
    if raw.get("invite_only"):
        tags.append(f"{YELLOW}🔒 INVITE ONLY{RESET}")
    if raw.get("organization"):
        tags.append(f"{DIM}by {raw['organization']}{RESET}")
    tags_str = f"  {'  '.join(tags)}" if tags else ""

    print(f"\n  {BOLD}{h.score:3d}/100{RESET}  {h.name}{deep_marker}{tags_str}")

    # Score breakdown
    parts = [f"prize={bd.get('prize_pool', 0)}", f"sponsor={bd.get('sponsor_prizes', 0)}",
             f"deadline={bd.get('deadline_buffer', 0)}", f"theme={bd.get('theme_match', 0)}",
             f"comp={bd.get('competition_size', 0)}"]
    if bd.get("featured_bonus"):
        parts.append(f"feat=+{bd['featured_bonus']}")
    if bd.get("invite_only_penalty"):
        parts.append(f"invite={bd['invite_only_penalty']}")
    if bd.get("prize_diversity"):
        parts.append(f"div=+{bd['prize_diversity']}")
    print(f"         {DIM}{' '.join(parts)}{RESET}")

    # Quick stats line
    time_left = raw.get("time_left", f"{h.days_until_deadline}d left")
    participants_str = f"{h.total_participants:,} registered" if h.total_participants else "? registered"
    cash_str = f"{raw.get('prizes_cash_count', '?')} cash prizes" if raw.get('prizes_cash_count') else ""
    stats_parts = [f"${prize_total:,.0f}", time_left, participants_str, h.platform, marker]
    if cash_str:
        stats_parts.insert(2, cash_str)
    print(f"         {DIM}{' · '.join(stats_parts)}{RESET}")
    print(f"         {DIM}{h.url}{RESET}")
    if raw.get("location") and raw["location"] != "Online":
        print(f"         {DIM}📍 {raw['location']}{RESET}")

    if not verbose:
        return

    # Theme & description
    if h.theme:
        print(f"         {CYAN}Theme:{RESET} {h.theme[:120]}")
    if h.description and len(h.description) > 10:
        print(f"         {CYAN}About:{RESET} {h.description[:250]}...")

    # Prizes breakdown
    if len(h.prizes) > 1:
        print(f"         {CYAN}Prizes ({len(h.prizes)}):{RESET}")
        for p in h.prizes[:10]:
            amt = f"${p.amount:,.0f}" if p.amount else "TBD"
            sponsor = f" ({p.sponsor})" if p.sponsor else ""
            print(f"           · {p.name}: {amt}{sponsor}")

    # Tracks
    if h.tracks:
        print(f"         {CYAN}Tracks ({len(h.tracks)}):{RESET}")
        for t in h.tracks[:8]:
            sponsor = f" [{t.sponsor}]" if t.sponsor else ""
            print(f"           · {t.name}{sponsor}")

    # Judges
    if h.judges:
        print(f"         {CYAN}Judges ({len(h.judges)}):{RESET}")
        for j in h.judges[:8]:
            role = f" — {j.title}, {j.company}" if j.title else ""
            print(f"           · {j.name}{role}")

    # Judging criteria
    if h.judging_criteria:
        print(f"         {CYAN}Judging:{RESET} {', '.join(h.judging_criteria[:6])}")

    # Sponsor APIs
    if h.sponsor_techs:
        print(f"         {CYAN}Sponsor APIs:{RESET}")
        for s in h.sponsor_techs[:8]:
            docs = f" → {s.docs_url}" if s.docs_url else ""
            print(f"           · {s.sponsor}: {s.api_name}{docs}")

    # Community links
    if h.community_links:
        grouped: dict[str, list[str]] = {}
        for cl in h.community_links:
            grouped.setdefault(cl.platform, []).append(cl.url)
        print(f"         {CYAN}Community & Resources ({len(h.community_links)}):{RESET}")
        for platform, urls in grouped.items():
            for url in urls[:3]:
                print(f"           · [{platform}] {url}")

    # Research
    if h.research:
        papers = [r for r in h.research if r.source == "arxiv"]
        repos = [r for r in h.research if r.source == "github"]
        others = [r for r in h.research if r.source not in ("arxiv", "github")]
        print(f"         {CYAN}Research ({len(h.research)} items):{RESET}")
        for r in (papers + repos + others)[:10]:
            print(f"           · [{r.source}] {r.title[:80]}")
            print(f"             {DIM}{r.url}{RESET}")

    # Rules snippet
    if h.rules:
        print(f"         {CYAN}Rules:{RESET} {h.rules[:250]}...")

    # FAQs
    if h.faqs:
        print(f"         {CYAN}FAQs ({len(h.faqs)}):{RESET}")
        for faq in h.faqs[:5]:
            text = str(faq) if not isinstance(faq, str) else faq
            print(f"           · {text[:120]}")

    # Allowed technologies
    if h.allowed_techs:
        print(f"         {CYAN}Allowed Tech:{RESET} {', '.join(h.allowed_techs[:10])}")


async def cmd_scout(args):
    """Discover and score hackathons."""
    deep = not getattr(args, 'shallow', False)
    mode = "deep" if deep else "shallow"
    section(f"Scouting hackathons ({mode} mode)...")

    from agents.python.intelligence.hackathon_scout import run_scout
    qualified, all_briefs = await run_scout(dry_run=args.dry_run, return_all=True, deep=deep)

    # Show all scored hackathons with full intel
    if all_briefs:
        section(f"Scored {len(all_briefs)} hackathons:")
        for h in all_briefs:
            _print_hackathon_detail(h, verbose=deep)

    if not qualified:
        warn("No qualifying hackathons found this cycle (need score >= 65).")
        if all_briefs:
            top = all_briefs[0]
            info(f"Closest: {top.name} at {top.score}/100")
        return

    total_prize = sum(sum(p.amount or 0 for p in h.prizes) for h in qualified)
    section(f"{len(qualified)} Qualifying Hackathons  (score >= 65 · ${total_prize:,.0f} total prize pool)")
    print()
    print(f"  {BOLD}{'#':>2}  {'SCORE':>5}  {'DAYS':>5}  {'PRIZE':>10}  STATUS      NAME{RESET}")
    print(f"  {DIM}{'─' * 2}  {'─' * 5}  {'─' * 5}  {'─' * 10}  {'─' * 10}  {'─' * 35}{RESET}")

    for idx, h in enumerate(qualified, 1):
        prize_total = sum(p.amount or 0 for p in h.prizes)
        status = f"{GREEN}REGISTERED{RESET}" if not args.dry_run and h.registration_open else f"{YELLOW}DRY RUN{RESET}"

        if h.score >= 80:
            sc = f"{GREEN}{BOLD}{h.score:>5}{RESET}"
        elif h.score >= 65:
            sc = f"{GREEN}{h.score:>5}{RESET}"
        else:
            sc = f"{YELLOW}{h.score:>5}{RESET}"

        if isinstance(h.days_until_deadline, int) and h.days_until_deadline <= 3:
            dc = f"{RED}{h.days_until_deadline:>4}d{RESET}"
        elif isinstance(h.days_until_deadline, int) and h.days_until_deadline <= 7:
            dc = f"{YELLOW}{h.days_until_deadline:>4}d{RESET}"
        else:
            dc = f"{DIM}{str(h.days_until_deadline):>4}d{RESET}"

        name = h.name[:35]
        print(f"  {DIM}{idx:>2}{RESET}  {sc}  {dc}  {'$' + f'{prize_total:,.0f}':>10}  {status:<10}  {name}")

    print()
    if not args.dry_run:
        info("Calendar events scheduled. Check your Google Calendar.")
    info(f"Run {BOLD}forge status{RESET} to see the full dashboard.")
    info(f"Run {BOLD}forge ls{RESET} for a quick list of all tracked hackathons.")


async def cmd_run(args):
    """Full autonomous build cycle."""
    from agents.python.orchestrator.commander import run, run_listener

    if args.listen:
        section("Starting Forge in daemon mode...")
        info("Listening for new hackathons from Scout")
        info("Press Ctrl+C to stop")
        await run_listener()
    elif args.id:
        section(f"Starting Forge for: {args.id}")
        result = await run(args.id)
        if result.get("submission_url"):
            ok(f"Submitted: {result['submission_url']}")
        else:
            warn(f"Run ended in phase: {result.get('phase', 'unknown')}")
    else:
        err("Specify --id <hackathon-id> or use --listen for daemon mode")
        print("  Run 'forge ls' to see active hackathons")


async def cmd_status(args):
    """Interactive dashboard showing ALL tracked hackathons + agent details."""
    redis = get_redis()

    if args.id:
        hackathon_ids = [args.id]
    else:
        keys = await redis.keys("hackathon:*:brief")
        hackathon_ids = sorted([k.split(":")[1] for k in keys])

    if not hackathon_ids:
        warn("No active hackathons. Run 'forge scout' to find some.")
        await redis.aclose()
        return

    from config.agents_config import ALL_AGENTS

    # Load all briefs
    briefs_data: list[tuple[str, dict]] = []
    for hid in hackathon_ids:
        raw = await redis.get(f"hackathon:{hid}:brief")
        if raw:
            briefs_data.append((hid, json.loads(raw)))
    briefs_data.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    total_count = len(briefs_data)
    per_page = getattr(args, "per_page", 15)
    page = getattr(args, "page", 1)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_count)
    page_data = briefs_data[start_idx:end_idx]

    # ── Scoreboard ────────────────────────────────────────────────────────
    page_label = f"  page {page}/{total_pages}" if total_pages > 1 else ""
    section(f"Hackathon Dashboard  ({total_count} tracked{page_label})")
    print()
    print(f"  {BOLD}{'#':>3}  {'SCORE':>5}  {'DAYS':>5}  {'PRIZE':>10}  {'REG':>6}  NAME{RESET}")
    print(f"  {DIM}{'─' * 3}  {'─' * 5}  {'─' * 5}  {'─' * 10}  {'─' * 6}  {'─' * 42}{RESET}")

    for idx, (hid, brief) in enumerate(page_data, start_idx + 1):
        score = brief.get("score", 0)
        days = brief.get("days_until_deadline", "?")
        prize = sum(p.get("amount") or 0 for p in brief.get("prizes", []))
        participants = brief.get("total_participants")
        name = brief.get("name", hid)[:42]
        qualified = score >= 65

        if score >= 80:
            sc = f"{GREEN}{BOLD}{score:>5}{RESET}"
        elif score >= 65:
            sc = f"{GREEN}{score:>5}{RESET}"
        elif score >= 50:
            sc = f"{YELLOW}{score:>5}{RESET}"
        else:
            sc = f"{DIM}{score:>5}{RESET}"

        if isinstance(days, int) and days <= 3:
            dc = f"{RED}{days:>4}d{RESET}"
        elif isinstance(days, int) and days <= 7:
            dc = f"{YELLOW}{days:>4}d{RESET}"
        else:
            dc = f"{DIM}{str(days):>4}d{RESET}"

        reg_str = f"{participants:>6,}" if participants else f"{'—':>6}"
        star = f" {GREEN}★{RESET}" if qualified else ""
        print(f"  {DIM}{idx:>3}{RESET}  {sc}  {dc}  {'$' + f'{prize:,.0f}':>10}  {reg_str}  {name}{star}")

    # Legend + pagination nav
    print(f"\n  {DIM}{GREEN}★{RESET}{DIM} = qualifies (≥65)  ·  "
          f"{RED}red{RESET}{DIM} = ≤3d left  ·  "
          f"{YELLOW}yellow{RESET}{DIM} = ≤7d left{RESET}")

    if total_pages > 1:
        nav_parts = []
        if page > 1:
            nav_parts.append(f"{BOLD}forge status -p {page - 1}{RESET}{DIM}")
        nav_parts.append(f"page {page}/{total_pages}")
        if page < total_pages:
            nav_parts.append(f"{BOLD}forge status -p {page + 1}{RESET}{DIM}")
        print(f"  {DIM}◀ {'  ·  '.join(nav_parts)} ▶{RESET}")

    # ── Agent Detail ──────────────────────────────────────────────────────
    if args.id:
        detail_set = briefs_data
    else:
        detail_set = page_data[:5]
        if len(page_data) > 5:
            print(f"\n  {DIM}Showing agent grid for top 5 on this page. "
                  f"Use {BOLD}forge status --id <ID>{RESET}{DIM} for details.{RESET}")

    LAYER_AGENTS = {
        "intelligence": ["hackathon_scout", "competitor_analyst", "judge_profiler", "sponsor_researcher"],
        "strategy":     ["strategy_director", "pm", "tech_architect"],
        "design":       ["ui_ux_designer"],
        "build":        ["frontend_engineer", "backend_engineer", "integration_engineer", "test_engineer", "devops", "security"],
        "verify":       ["code_reviewer", "ux_auditor", "performance"],
        "polish":       ["polish", "copy_writer", "data_seeder", "brand"],
        "submission":   ["demo_producer", "pitch_writer", "submission"],
        "infra":        ["memory_keeper", "monitor", "calendar", "knowledge_updater", "outcome_tracker"],
    }
    ICONS = {
        "done": f"{GREEN}✓{RESET}", "in-progress": f"{YELLOW}⟳{RESET}",
        "pending": f"{DIM}·{RESET}", "failed": f"{RED}✗{RESET}", None: f"{DIM}·{RESET}",
    }

    for hackathon_id, brief in detail_set:
        name = brief.get("name", hackathon_id)
        score = brief.get("score", 0)
        days = brief.get("days_until_deadline", "?")
        url = brief.get("url", "")
        platform = brief.get("platform", "")

        print(f"\n  {'━' * 60}")
        print(f"  {BOLD}{name}{RESET}  {DIM}{score}/100 · {days}d · {platform}{RESET}")
        print(f"  {DIM}{url}{RESET}")
        print(f"  {DIM}ID: {hackathon_id}{RESET}\n")

        for layer, agent_ids in LAYER_AGENTS.items():
            parts = []
            for aid in agent_ids:
                task_raw = await redis.get(f"task:{hackathon_id}:{aid}")
                task = json.loads(task_raw) if task_raw else {}
                status = task.get("status")
                icon = ICONS.get(status, ICONS[None])
                aname = ALL_AGENTS[aid].name if aid in ALL_AGENTS else aid
                parts.append(f"{icon} {aname}")
            print(f"  {CYAN}{layer:<12}{RESET}  {'  '.join(parts)}")

        # Pending checkpoints
        for cp_name, cp_label in [
            ("concept_approval", "Concept"), ("design_approval", "Design"),
            ("quality_review", "Quality"), ("submission_approval", "Submit"),
        ]:
            cp_raw = await redis.get(f"checkpoint:{hackathon_id}:{cp_name}")
            if cp_raw == "pending":
                short = cp_name.split("_")[0]
                print(f"\n  {YELLOW}⚡ ACTION NEEDED:{RESET} {cp_label} → {BOLD}forge approve {short} --id {hackathon_id}{RESET}")

        try:
            from config.forge_tools import get_run_cost_summary
            cost = await get_run_cost_summary(redis, hackathon_id)
            if cost["total_usd"] > 0:
                top = sorted(cost["by_agent"].items(), key=lambda x: x[1]["cost_usd"], reverse=True)[:2]
                top_str = ", ".join(f"{a}: ${v['cost_usd']:.3f}" for a, v in top)
                print(f"\n  {DIM}Cost: ${cost['total_usd']:.3f} · {cost['total_tokens']:,} tokens · {top_str}{RESET}")
        except Exception:
            pass  # cost tracking is optional — don't block the dashboard

    print()
    await redis.aclose()


async def cmd_approve(args):
    """Human checkpoint interface."""
    redis = get_redis()

    checkpoint = args.checkpoint
    hackathon_id = args.id

    if not hackathon_id:
        # Find the first hackathon with a pending checkpoint
        keys = await redis.keys("checkpoint:*:*")
        for key in keys:
            raw = await redis.get(key)
            if raw == "pending":
                parts = key.split(":")
                hackathon_id = parts[1]
                checkpoint = parts[2]
                break

    if not hackathon_id:
        warn("No pending checkpoints found.")
        await redis.aclose()
        return

    key = f"checkpoint:{hackathon_id}:{checkpoint}"
    raw = await redis.get(key)

    if checkpoint == "concept_approval":
        concepts_raw = await redis.get(f"hackathon:{hackathon_id}:concepts")
        if concepts_raw:
            concepts_data = json.loads(concepts_raw)
            concepts = concepts_data.get("concepts", [])
            section(f"Choose a concept for: {hackathon_id}")
            for c in concepts:
                print(f"\n  {BOLD}[{c['rank']}]{RESET} {c['project_name']}  {DIM}score: {c.get('total_score', '?')}/100{RESET}")
                print(f"       {c.get('tagline', '')}")
                print(f"       {DIM}Why it wins: {c.get('why_it_wins', '')[:120]}...{RESET}")

            print()
            choice = input(f"  Enter concept number [1-{len(concepts)}] (default: recommended): ").strip()
            concept_index = (int(choice) - 1) if choice.isdigit() else concepts_data.get("recommended_concept", 1) - 1

            await redis.set(key, json.dumps({
                "approved": True,
                "concept_index": concept_index,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "approved_by": "human",
            }), ex=86400)
            ok(f"Concept {concept_index + 1} approved. Forge is building.")

    elif checkpoint in ("design_approval", "quality_review", "submission_approval"):
        data_raw = await redis.get(key)
        data = json.loads(data_raw) if data_raw and data_raw != "pending" else {}

        section(f"Checkpoint: {checkpoint.replace('_', ' ').title()}")
        if data.get("materials"):
            for k, v in data["materials"].items():
                if v:
                    print(f"  {CYAN}{k}:{RESET} {v}")

        print()
        confirm = input(f"  Approve? [y/N] ").strip().lower()
        if confirm == "y":
            await redis.set(key, json.dumps({
                "approved": True,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "approved_by": "human",
            }), ex=86400)
            ok(f"Approved. Forge continues.")
        else:
            warn("Not approved. Forge waits.")

    await redis.aclose()


async def cmd_plan(args):
    """Show the build plan for a hackathon run (Feature 6: /ultraplan)."""
    redis = get_redis()

    hackathon_id = args.id
    if not hackathon_id:
        keys = await redis.keys("hackathon:*:brief")
        if not keys:
            warn("No active hackathons. Run 'forge scout' first.")
            await redis.aclose()
            return
        hackathon_id = keys[0].split(":")[1]

    plan_raw = await redis.get(f"hackathon:{hackathon_id}:build_plan")
    await redis.aclose()

    if not plan_raw:
        warn(f"No build plan yet for {hackathon_id}. Plan is generated after design phase.")
        info("Run 'forge status' to see current phase.")
        return

    plan = json.loads(plan_raw)
    section(f"Build Plan — {hackathon_id}")

    tasks = plan.get("tasks", [])
    critical_path = set(plan.get("critical_path", []))
    total_hours   = plan.get("total_estimated_hours", 0)
    biggest_risk  = plan.get("biggest_risk", "")
    demo_comps    = plan.get("demo_path_components", [])

    RISK_COLOR = {"low": GREEN, "medium": YELLOW, "high": RED}

    print(f"\n  {BOLD}Tasks ({len(tasks)}){RESET}  ·  {total_hours:.1f}h total estimated\n")
    for t in tasks:
        agent     = t.get("agent", "?")
        desc      = t.get("description", "")
        deps      = t.get("depends_on", [])
        hours     = t.get("estimated_hours", 0)
        risk      = t.get("risk", "low")
        is_crit   = agent in critical_path
        cp_marker = f" {CYAN}[critical path]{RESET}" if is_crit else ""
        risk_col  = RISK_COLOR.get(risk, DIM)
        dep_str   = f"  {DIM}after: {', '.join(deps)}{RESET}" if deps else ""
        print(f"  {GREEN}▸{RESET} {BOLD}{agent:<22}{RESET}  {hours:.1f}h  "
              f"{risk_col}{risk:<6}{RESET}{cp_marker}")
        print(f"    {DIM}{desc[:72]}{RESET}{dep_str}")
        print()

    if demo_comps:
        print(f"  {BOLD}Demo path components (judges see these):{RESET}")
        for c in demo_comps:
            print(f"  {CYAN}·{RESET} {c}")
        print()

    if biggest_risk:
        print(f"  {YELLOW}⚠ Biggest risk:{RESET} {biggest_risk[:100]}")

    print()


async def cmd_knowledge(args):
    """Update Forge's design and strategy intelligence."""
    section("Updating Forge intelligence...")
    info("Researching: trending UI libraries, winning concepts, current stacks")
    info("This takes ~2 minutes (5 parallel research tasks)")

    from agents.python.infra.knowledge_updater import run_knowledge_update
    result = await run_knowledge_update(dry_run=args.dry_run)

    if args.dry_run:
        warn("Dry run — no changes written")
    else:
        ok(f"Knowledge updated: {result.get('date')}")
        ok(f"Sections updated: {', '.join(result.get('sections_updated', []))}")
        ok(f"Static sections preserved: {', '.join(result.get('sections_preserved', []))}")


async def cmd_ls(args):
    """List ALL active hackathons with quick stats."""
    redis = get_redis()
    keys = await redis.keys("hackathon:*:brief")

    if not keys:
        warn("No active hackathons. Run 'forge scout' to find some.")
        await redis.aclose()
        return

    rows: list[tuple[str, dict]] = []
    for key in keys:
        hid = key.split(":")[1]
        raw = await redis.get(key)
        if raw:
            rows.append((hid, json.loads(raw)))
    rows.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    qualified = [r for r in rows if r[1].get("score", 0) >= 65]
    total_prize = sum(sum(p.get("amount") or 0 for p in b.get("prizes", [])) for _, b in rows)

    total_count = len(rows)
    show_all = getattr(args, "show_all", False)
    per_page = total_count if show_all else getattr(args, "per_page", 20)
    page = 1 if show_all else getattr(args, "page", 1)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_count)
    page_rows = rows[start_idx:end_idx]

    page_label = f"  page {page}/{total_pages}" if total_pages > 1 else ""
    section(
        f"Active Hackathons  ({total_count} total · {len(qualified)} qualified "
        f"· ${total_prize:,.0f} in prizes{page_label})"
    )
    print()
    print(f"  {BOLD}{'#':>3}  {'SCORE':>5}  {'DAYS':>5}  {'PRIZE':>10}  NAME{RESET}")
    print(f"  {DIM}{'─' * 3}  {'─' * 5}  {'─' * 5}  {'─' * 10}  {'─' * 42}{RESET}")

    for idx, (hid, brief) in enumerate(page_rows, start_idx + 1):
        score = brief.get("score", 0)
        days = brief.get("days_until_deadline", "?")
        prize = sum(p.get("amount") or 0 for p in brief.get("prizes", []))
        name = brief.get("name", hid)[:40]
        featured = brief.get("featured", False)
        invite = brief.get("invite_only", False)

        if score >= 80:
            sc = f"{GREEN}{BOLD}{score:>5}{RESET}"
        elif score >= 65:
            sc = f"{GREEN}{score:>5}{RESET}"
        elif score >= 50:
            sc = f"{YELLOW}{score:>5}{RESET}"
        else:
            sc = f"{DIM}{score:>5}{RESET}"

        if isinstance(days, int) and days <= 3:
            dc = f"{RED}{days:>4}d{RESET}"
        elif isinstance(days, int) and days <= 7:
            dc = f"{YELLOW}{days:>4}d{RESET}"
        else:
            dc = f"{DIM}{str(days):>4}d{RESET}"

        badges = ""
        if featured:
            badges += f" {GREEN}★{RESET}"
        if invite:
            badges += f" {RED}🔒{RESET}"
        if score >= 65:
            badges += f" {GREEN}GO{RESET}"

        print(f"  {DIM}{idx:>3}{RESET}  {sc}  {dc}  {'$' + f'{prize:,.0f}':>10}  {name}{badges}")
        print(f"      {' ' * 5}  {' ' * 5}  {' ' * 10}  {DIM}{hid}{RESET}")

    # Pagination nav
    if total_pages > 1:
        nav_parts = []
        if page > 1:
            nav_parts.append(f"{BOLD}forge ls -p {page - 1}{RESET}{DIM}")
        nav_parts.append(f"page {page}/{total_pages}")
        if page < total_pages:
            nav_parts.append(f"{BOLD}forge ls -p {page + 1}{RESET}{DIM}")
        print(f"\n  {DIM}◀ {'  ·  '.join(nav_parts)} ▶{RESET}")
        print(f"  {DIM}Show all: {BOLD}forge ls --all{RESET}")
    print(f"\n  {DIM}Use {BOLD}forge status{RESET}{DIM} for agent grid · {BOLD}forge status --id <ID>{RESET}{DIM} for detail{RESET}")
    await redis.aclose()


async def cmd_test(args):
    """Run system health checks."""
    section("Running Forge health checks...")

    checks = []

    # ElectronHub
    try:
        from config.electronhub import complete
        result = await complete(
            task="classify-hackathon",
            messages=[{"role": "user", "content": "Reply: FORGE_OK"}],
        )
        checks.append(("ElectronHub", "FORGE_OK" in result or "OK" in result))
    except Exception as e:
        checks.append(("ElectronHub", False, str(e)))

    # Browser layer
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(
                os.environ.get("BROWSER_SERVER_URL", "http://localhost:3100") + "/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                checks.append(("Browser layer", r.status == 200))
    except Exception as e:
        checks.append(("Browser layer", False, "not running"))

    # Redis
    try:
        r = get_redis()
        await r.ping()
        await r.aclose()
        checks.append(("Redis", True))
    except Exception as e:
        checks.append(("Redis", False, str(e)))

    # Qdrant
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get("http://localhost:6333/readyz", timeout=aiohttp.ClientTimeout(total=5)) as r:
                checks.append(("Qdrant", r.status == 200))
    except Exception:
        checks.append(("Qdrant", False, "not running"))

    # Design constitution
    try:
        from config.design_constitution import STATIC_DESIGN_LAWS, LIVING_KNOWLEDGE, REFERENCE_SITES
        checks.append(("Design constitution", len(STATIC_DESIGN_LAWS) > 100 and "composio.dev" in REFERENCE_SITES))
    except Exception as e:
        checks.append(("Design constitution", False, str(e)))

    print()
    all_pass = True
    for check in checks:
        name, passed = check[0], check[1]
        detail = check[2] if len(check) > 2 else ""
        if passed:
            ok(f"{name}")
        else:
            err(f"{name}{f'  {DIM}{detail}{RESET}' if detail else ''}")
            all_pass = False

    print()
    if all_pass:
        ok(f"{BOLD}All systems operational. Forge is ready.{RESET}")
    else:
        warn("Some systems need attention. Run 'bash scripts/start.sh' to start services.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    header()

    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge — autonomous hackathon swarm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # scout
    p_scout = sub.add_parser("scout", help="Discover and score this week's hackathons")
    p_scout.add_argument("--dry-run", action="store_true", help="Don't register, just score")
    p_scout.add_argument("--shallow", action="store_true", help="Skip deep scrape / community / research phases")

    # run
    p_run = sub.add_parser("run", help="Full autonomous build cycle")
    p_run.add_argument("--id", metavar="HACKATHON_ID", help="Run specific hackathon")
    p_run.add_argument("--listen", action="store_true", help="Daemon mode — listen for Scout triggers")

    # status
    p_status = sub.add_parser("status", help="Dashboard — scoreboard + agent grid for ALL hackathons")
    p_status.add_argument("--id", metavar="HACKATHON_ID", help="Drill into a specific hackathon")
    p_status.add_argument("--page", "-p", type=int, default=1, help="Page number (default: 1)")
    p_status.add_argument("--per-page", "-n", type=int, default=15, help="Hackathons per page (default: 15)")

    # approve
    p_approve = sub.add_parser("approve", help="Human checkpoint interface")
    p_approve.add_argument("checkpoint", nargs="?", choices=["concept", "design", "quality", "submit"], help="Which checkpoint")
    p_approve.add_argument("--id", metavar="HACKATHON_ID", help="Hackathon ID (auto-detected if omitted)")

    # plan
    p_plan = sub.add_parser("plan", help="Show the build plan (tasks, critical path, risks)")
    p_plan.add_argument("--id", metavar="HACKATHON_ID", help="Hackathon ID")

    # knowledge
    p_knowledge = sub.add_parser("knowledge", help="Update design + strategy intelligence")
    p_knowledge.add_argument("--dry-run", action="store_true", help="Preview without writing")

    # ls
    p_ls = sub.add_parser("ls", help="Quick list of ALL active hackathons with scores")
    p_ls.add_argument("--page", "-p", type=int, default=1, help="Page number (default: 1)")
    p_ls.add_argument("--per-page", "-n", type=int, default=20, help="Hackathons per page (default: 20)")
    p_ls.add_argument("--all", "-a", action="store_true", dest="show_all", help="Show all (no pagination)")

    # test
    sub.add_parser("test", help="Run system health checks")

    # web
    p_web = sub.add_parser("web", help="Start web dashboard for remote approval from any device")
    p_web.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p_web.add_argument("--port", type=int, default=3000, help="Port (default: 3000)")

    # calendar
    sub.add_parser("calendar-auth", help="Google Calendar service account setup & verification")
    sub.add_parser("calendar-test", help="Create a test event to verify Google Calendar works")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "calendar-auth":
        from agents.python.infra.monitor_and_calendar import run_calendar_auth
        run_calendar_auth()
        return

    if args.command == "web":
        from forge_web import start as start_web
        print(f"\n{BOLD}Starting Forge web dashboard on http://{args.host}:{args.port}{RESET}")
        token = os.environ.get("FORGE_WEB_TOKEN", "")
        if token:
            print(f"  Auth token set — append ?token={token} to login\n")
        else:
            print(f"  {DIM}No FORGE_WEB_TOKEN set — dashboard is open (set one in forge.secrets){RESET}\n")
        start_web(args.host, args.port)
        return

    async def run():
        if args.command == "scout":
            await cmd_scout(args)
        elif args.command == "run":
            await cmd_run(args)
        elif args.command == "status":
            await cmd_status(args)
        elif args.command == "approve":
            # Map short names to full checkpoint names
            if args.checkpoint:
                mapping = {"concept": "concept_approval", "design": "design_approval",
                           "quality": "quality_review", "submit": "submission_approval"}
                args.checkpoint = mapping.get(args.checkpoint, args.checkpoint)
            await cmd_approve(args)
        elif args.command == "plan":
            await cmd_plan(args)
        elif args.command == "knowledge":
            await cmd_knowledge(args)
        elif args.command == "ls":
            await cmd_ls(args)
        elif args.command == "test":
            await cmd_test(args)
        elif args.command == "calendar-test":
            from agents.python.infra.monitor_and_calendar import calendar_test
            print(f"\n{BOLD}Testing Google Calendar integration...{RESET}\n")
            success = await calendar_test()
            if success:
                ok("Google Calendar is working! Check your calendar for the test event.")
            else:
                err("Google Calendar test failed. Run 'forge calendar-auth' first.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
