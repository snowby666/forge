# Forge Documentation

**30 agents. One submission. Every time.**

Forge is an autonomous hackathon swarm. It discovers opportunities, builds full-stack projects, and submits — while you show up for 4 checkpoints (~55 minutes total).

---

## Contents

| Doc | What's in it |
|---|---|
| [01 — Architecture](./01-architecture.md) | Full system diagram, language split, communication model, crash recovery |
| [02 — Agent Roster](./02-agent-roster.md) | All 30 agents with roles, SOP artifacts, tiers, failure modes. Includes Outcome Tracker (agent 30). |
| [03 — Execution Flow](./03-execution-flow.md) | Phase-by-phase timeline, Gantt chart, Commander state machine, dependency graph |
| [04 — LLM Routing](./04-llm-routing.md) | ElectronHub tiers, complete task→model table (50 entries), fallback chain |
| [05 — Design Constitution](./05-design-constitution.md) | Reference sites, static laws, anti-slop rules, living knowledge system |
| [06 — Memory System](./06-memory-system.md) | Mem0 + Qdrant architecture, reuse loop, 5 collections |
| [07 — Infrastructure](./07-infrastructure.md) | Services, ports, Redis schema, PostgreSQL, Daytona sandboxes, cost |
| [08 — CLI Reference](./08-cli-reference.md) | Every `forge` command with full example output |
| [09 — Agent Development](./09-agent-development.md) | Adding agents, debugging runs, common mistakes |
| [10 — Hackathon Intelligence](./10-hackathon-intelligence.md) | Scoring rubric, concept methodology, what wins vs what loses |

---

## Quick navigation

| Goal | Start here |
|---|---|
| Get Forge running for the first time | [07 Infrastructure](./07-infrastructure.md) → [08 CLI](./08-cli-reference.md) |
| Understand the full system | [01 Architecture](./01-architecture.md) → [03 Execution Flow](./03-execution-flow.md) |
| Work on UI/design agents | [05 Design Constitution](./05-design-constitution.md) |
| Add or modify an agent | [09 Agent Development](./09-agent-development.md) |
| Debug a failed run | [09 Agent Development](./09-agent-development.md#debugging-a-failed-run) |
| Understand LLM costs | [04 LLM Routing](./04-llm-routing.md) |
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
forge knowledge  ← update design + strategy intelligence
```
