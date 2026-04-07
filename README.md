# Forge

**30 agents. One submission. Every time.**

Forge is an autonomous hackathon swarm. It discovers opportunities, builds full-stack
projects, and submits — while you show up for 4 checkpoints totaling ~55 minutes.

```
forge scout          discover + score this week's hackathons
forge run            full autonomous build cycle (after scout registers you)
forge status         live view of all 30 agents
forge approve        human checkpoint interface
forge web            launch the web dashboard (browser UI)
forge delete         remove a hackathon and all data
forge reroll         reset strategy/design, keep intelligence
forge plan           re-plan project with existing intelligence
forge knowledge      update design + strategy intelligence
```

LLM routing: [ElectronHub](https://api.electronhub.ai/v1)
Browser: Stagehand v3 + Browserbase
Server: Python 3.11+ (all agents) + TypeScript (browser layer only)

---

## The 30 agents

```
Layer 0 — Command
  Commander              LangGraph orchestrator, PostgreSQL checkpoints

Layer 1 — Intelligence (parallel, run first)
  Hackathon Scout        Score and register from Devpost/MLH/Lablab/Devfolio
  Competitor Analyst     Past winner analysis, gap identification
  Judge Profiler         Panel research — what will resonate with THESE judges
  Sponsor Researcher     Prize-per-hour ranking, integration plans

Layer 2 — Strategy
  Strategy Director      3 ranked concepts from intelligence synthesis
  PM                     Sprint plan, 2 features max, 90-second demo path
  Tech Architect         DB schema + API contract (published immediately)

Layer 3 — Build (parallel)
  UI/UX Designer         Stitch → Figma MCP → DESIGN.md
                         Standard: composio.dev, hex.tech, linear.app
  Frontend Engineer      Next.js 14 + shadcn/ui + Vercel AI SDK
  Backend Engineer       FastAPI + PostgreSQL (publishes contract immediately)
  Integration Engineer   Sponsor APIs, prize eligibility
  Test Engineer          Playwright e2e, pytest, demo path coverage
  DevOps                 GitHub Actions, Vercel, Railway
  Security Agent         Secret scan, OWASP, dependency CVEs

Layer 4 — Verification (continuous)
  Code Reviewer          PR gating, TypeScript quality
  UX Auditor             Anti-slop guardian. Veto power. Score ≥7.0 required.
  Performance Agent      Lighthouse, Core Web Vitals, mobile

Layer 5 — Polish (parallel)
  Polish Agent           Micro-interactions, loading/empty states
  Copy Writer            All generic text rewritten, judge-calibrated
  Data Seeder            Realistic demo data, golden path setup
  Brand Agent            Logo, favicon, og:image

Layer 6 — Submission
  Demo Producer          ElevenLabs narration + Playwright recording + ffmpeg
  Pitch Writer           readmeai README + Gamma deck + submission copy
  Submission Agent       Stagehand fills the form, checks all prize categories

Layer 7 — Infrastructure (always running)
  Memory Keeper          Mem0 + Qdrant — learns from every hackathon
  Monitor                Cost tracking, circuit breakers, Discord alerts
  Calendar Agent         Google Calendar checkpoints
  Knowledge Updater      Updates design + strategy intelligence via web research
  Outcome Tracker        Closes learning loop — scrapes results, feeds memory, adapts strategy
```

---

## Quick start

### Linux / macOS / WSL2

```bash
# 1. Bootstrap (creates .venv automatically)
bash scripts/setup.sh

# 2. Activate the virtual environment (required every new terminal)
source .venv/bin/activate

# 3. Add API keys
nano .env                 # Required: ELECTRONHUB_API_KEY

# 4. Start all services
bash scripts/start.sh

# 5. Verify everything works
python scripts/test_run.py --dry-run

# 5. Update knowledge before first run
python3 agents/python/infra/knowledge_updater.py

# 6. Start listening for hackathons
python3 agents/python/orchestrator/commander.py --listen
```

### Windows

**Recommended: use WSL2** for full GPU and Daytona support.
Install WSL2: `wsl --install` in PowerShell (admin), then follow the Linux instructions above.

**Native Windows (Docker Desktop + Git Bash):**

```powershell
# PowerShell (run once to allow scripts)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup.ps1
```

```bat
# Git Bash
bash scripts/setup.sh
bash scripts/start.sh

# Forge CLI on Windows (use python explicitly)
python forge scout
python forge status
python forge approve
```

Or use the included `forge.cmd` wrapper:

```bat
forge.cmd scout
forge.cmd status

# 7. Or run a specific hackathon
python agents/python/orchestrator/commander.py --hackathon-id devpost-123
```

---

## The design standard

Forge's UI agents are calibrated to these reference sites:
- **composio.dev** — dense terminal aesthetic, code blocks as UI, execution logs as content
- **hex.tech** — data notebook, information density as the luxury feature
- **riff.ai** — enterprise workflow builder, numbered steps, status everywhere
- **linear.app** — ultra-dark, keyboard-first, single accent color

The UX Auditor blocks submission if the output doesn't match this standard.
It scores 6 dimensions and requires ≥7.0 overall with zero anti-slop violations.

The full design constitution: `config/design_constitution.py`

---

## Self-updating intelligence

The Knowledge Updater agent runs before each hackathon cycle and updates
`LIVING_KNOWLEDGE` in `config/design_constitution.py` with:

- Current trending UI libraries and stacks
- What concept types are winning hackathons right now
- What judges are rewarding vs penalizing

Static sections (design laws, anti-slop rules, audit rubric, agent prompts) are frozen.
Only `LIVING_KNOWLEDGE` changes. The updater validates the file is valid Python and
all static sections are intact before writing.

```bash
python agents/python/infra/knowledge_updater.py --dry-run   # preview
python agents/python/infra/knowledge_updater.py             # apply
```

---

## Human checkpoints (~55 min total)

| Checkpoint | Time | What you decide |
|---|---|---|
| Concept pick | ~15 min | Choose from 3 ranked concepts with win-probability scores |
| Design approve | ~10 min | Review DESIGN.md + Figma before build starts |
| Quality review | ~20 min | Check live Vercel URL on desktop AND 375px mobile |
| Submit approval | ~10 min | Final review before Forge fills the form |

---

## Web dashboard

Forge includes a browser-based dashboard for monitoring and managing hackathons.

```bash
forge web              # launch API on :3001
# Or via Docker:
docker compose up -d api web
```

Features: real-time agent pipeline view, checkpoint approvals with concept selection, per-agent cost breakdown and execution times, live logs, hackathon management (run/reroll/delete from browser), system health monitoring, config editor.

Protected by `FORGE_WEB_TOKEN` in `.env` (auto-generated by deploy scripts if missing).

- **Backend**: `forge_web/` — FastAPI, modular routers, WebSocket real-time
- **Frontend**: `web/` — Next.js 15, shadcn/ui, Tailwind, framer-motion

---

## Key files

| File | Role |
|---|---|
| `config/design_constitution.py` | The design brain. Static laws + living knowledge. |
| `config/electronhub.py` | All LLM calls route through here. Never bypass. Cost tracking built in. |
| `config/agents_config.py` | All 30 agent definitions, prompts, SOP artifacts. |
| `config/forge_tools.py` | Tool protocol, cost tracker, concurrency graph. |
| `agents/python/orchestrator/commander.py` | LangGraph state machine. Entry point. |
| `agents/python/infra/knowledge_updater.py` | Self-updating intelligence system. |
| `forge_web/` | Web API package (FastAPI routers, services, auth). |
| `web/src/` | Dashboard frontend (Next.js, React, shadcn/ui). |
| `.cursorrules` | Cursor AI coding rules. Read before touching any code. |

---

## Cost

| Service | Cost | Notes |
|---|---|---|
| Browserbase | $49/mo | Bot detection bypass — required |
| ElevenLabs | $5/mo | Demo narration (free fallback: edge-tts) |
| Everything else | $0 | Self-hosted on your server |
| **Total fixed** | **~$54/mo** | |

Per-run LLM costs depend on the models used; tracked automatically via `config/electronhub.py` and visible on the web dashboard.
