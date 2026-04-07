# Forge Documentation

**30 agents. One submission. Every time.**

Forge is an autonomous hackathon swarm. It discovers opportunities, builds full-stack projects, and submits — while you show up for 4 checkpoints (~55 minutes total).

---

## Contents

| Doc | What's in it |
|---|---|
| [01 — Architecture](./01-architecture.md) | Full system diagram, language split, communication model, web dashboard, crash recovery |
| [02 — Agent Roster](./02-agent-roster.md) | All 30 agents with roles, SOP artifacts, tiers, failure modes. Includes Outcome Tracker (agent 30). |
| [03 — Execution Flow](./03-execution-flow.md) | Phase-by-phase timeline, Gantt chart, Commander state machine, dependency graph |
| [04 — LLM Routing](./04-llm-routing.md) | ElectronHub tiers, task→model table (50 entries), fallback chain, cost tracking |
| [05 — Design Constitution](./05-design-constitution.md) | Reference sites, static laws, anti-slop rules, living knowledge system |
| [06 — Memory System](./06-memory-system.md) | Mem0 + Qdrant architecture, reuse loop, 5 collections |
| [07 — Infrastructure](./07-infrastructure.md) | Services, ports, Redis schema, PostgreSQL, web dashboard, Docker Compose |
| [08 — CLI Reference](./08-cli-reference.md) | Every `forge` command with full example output |
| [09 — Agent Development](./09-agent-development.md) | Adding agents, debugging runs, common mistakes |
| [10 — Hackathon Intelligence](./10-hackathon-intelligence.md) | Scoring rubric, concept methodology, what wins vs what loses |

---

## Quick navigation

| Goal | Start here |
|---|---|
| Get Forge running for the first time | [07 Infrastructure](./07-infrastructure.md) → [08 CLI](./08-cli-reference.md) |
| Understand the full system | [01 Architecture](./01-architecture.md) → [03 Execution Flow](./03-execution-flow.md) |
| Use the web dashboard | [07 Infrastructure](./07-infrastructure.md#web-dashboard) → [08 CLI](./08-cli-reference.md#forge-web) |
| Work on UI/design agents | [05 Design Constitution](./05-design-constitution.md) |
| Add or modify an agent | [09 Agent Development](./09-agent-development.md) |
| Debug a failed run | [09 Agent Development](./09-agent-development.md#debugging-a-failed-run) |
| Understand LLM costs | [04 LLM Routing](./04-llm-routing.md#cost-tracking) |
| Understand why concepts win | [10 Hackathon Intelligence](./10-hackathon-intelligence.md) |

---

## System at a glance

```
forge scout      ← scrape + score + register
forge run        ← full autonomous cycle:
                    L1: Scout → Competitor Analyst → Judge Profiler → Sponsor Researcher
                    [human: concept pick, ~15 min]
                    L2: Strategy Director → PM → Tech Architect
                    [human: design approve, ~10 min]
                    L3: UI/UX Designer → Frontend + Backend + Integration + Test + DevOps + Security
                    L4: Code Reviewer + UX Auditor [veto] + Performance Agent
                    [human: quality review, ~20 min]
                    L5: Polish + Copy Writer + Data Seeder + Brand Agent
                    L6: Demo Producer + Pitch Writer
                    [human: submit approve, ~10 min]
                    L6: Submission Agent → SubmissionURL
                    L7: Outcome Tracker → store_outcome() → Memory loop closed
forge status     ← live agent view (check done pending failed)
forge approve    ← human checkpoint interface
forge web        ← launch web dashboard (Next.js + FastAPI)
forge delete     ← remove a hackathon and all its data
forge reroll     ← reset strategy/design, keep intelligence
forge knowledge  ← update design + strategy intelligence
```

### CLI reference (quick)

See [08 — CLI Reference](./08-cli-reference.md) for full examples. Highlights:

| Command | Purpose |
|---|---|
| `forge web` | Launch the web dashboard on `:3001` |
| `forge status -p N` / `forge status --per-page N` | Paginated dashboard |
| `forge ls -p N` / `forge ls --all` | Paginated list / show all hackathons |
| `forge delete --id <ID>` | Delete a hackathon and all associated data |
| `forge reroll --id <ID>` | Reset strategy/design, keeping intelligence |
| `forge plan --id <ID>` | Re-plan project without re-running intelligence |
| `forge calendar-auth` | Google Calendar service account setup |
| `forge calendar-test` | Verify calendar integration |
