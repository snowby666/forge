# 01 — Architecture

Forge is a 28-agent autonomous system organized into 8 layers. Python handles all agent logic. TypeScript handles browser automation only. They communicate via HTTP — never shared imports.

---

## System overview

```mermaid
graph TB
    subgraph HUMAN["👤 Human  (~55 min total)"]
        H1["Concept pick\n15 min"]
        H2["Design approve\n10 min"]
        H3["Quality review\n20 min"]
        H4["Submit approve\n10 min"]
    end

    subgraph L0["Layer 0 — Command"]
        CMD["Commander\nLangGraph · PostgreSQL checkpoints · Temporal"]
    end

    subgraph L1["Layer 1 — Intelligence  (parallel)"]
        SCO["Hackathon Scout"]
        CA["Competitor Analyst"]
        JP["Judge Profiler"]
        SR["Sponsor Researcher"]
    end

    subgraph L2["Layer 2 — Strategy"]
        SD["Strategy Director"]
        PM["PM"]
        TA["Tech Architect"]
    end

    subgraph L3["Layer 3 — Build  (parallel)"]
        UX["UI/UX Designer (*)"]
        FE["Frontend Engineer"]
        BE["Backend Engineer"]
        IE["Integration Engineer"]
        TE["Test Engineer"]
        DO["DevOps"]
        SEC["Security Agent"]
    end

    subgraph L4["Layer 4 — Verify  (continuous)"]
        CR["Code Reviewer"]
        UA["UX Auditor [veto]"]
        PA["Performance Agent"]
    end

    subgraph L5["Layer 5 — Polish  (parallel)"]
        PO["Polish Agent"]
        CW["Copy Writer"]
        DS["Data Seeder"]
        BA["Brand Agent"]
    end

    subgraph L6["Layer 6 — Submission"]
        DP["Demo Producer"]
        PW["Pitch Writer"]
        SA["Submission Agent"]
    end

    subgraph L7["Layer 7 — Infrastructure  (always running)"]
        MK["Memory Keeper"]
        MON["Monitor"]
        CAL["Calendar Agent"]
        KU["Knowledge Updater"]
    end

    subgraph INFRA["Self-hosted services"]
        PG[("PostgreSQL")]
        RD[("Redis")]
        QD[("Qdrant")]
        TMP["Temporal"]
        N8N["n8n"]
    end

    subgraph EXT["External"]
        EH["ElectronHub\nhttps://api.electronhub.ai/v1"]
        BB["Browserbase"]
        VCL["Vercel"]
        RLW["Railway"]
    end

    subgraph BROWSER["TypeScript — browser layer only"]
        BS["server.ts :3100\n/scrape /register /submit\n/screenshot /lighthouse /record-demo"]
    end

    CMD --> L1
    CMD --> L2
    CMD --> L3
    CMD --> L4
    CMD --> L5
    CMD --> L6

    H1 -.->|approve| CMD
    H2 -.->|approve| CMD
    H3 -.->|approve| CMD
    H4 -.->|approve| CMD

    L1 --> RD
    L2 --> RD
    L3 --> RD
    L4 --> RD
    L5 --> RD
    L6 --> RD
    CMD --> PG

    SCO -->|HTTP POST| BS
    SA -->|HTTP POST| BS
    UA -->|HTTP POST| BS
    DP -->|HTTP POST| BS
    BS --> BB

    L1 & L2 & L3 & L4 & L5 & L6 & L7 -->|all LLM calls| EH
    FE --> VCL
    BE --> RLW

    MK --> QD
    CMD --> TMP
    CAL --> N8N
    N8N -.->|webhook| CMD
```

---

## Language split

```mermaid
graph LR
    subgraph PY["Python 3.11+  (all 28 agents)"]
        direction TB
        C["config/electronhub.py\nconfig/agents_config.py\nconfig/design_constitution.py"]
        A["agents/python/**/*.py\n22 agent workers"]
        O["agents/python/orchestrator/commander.py\nLangGraph state machine"]
        I["agents/python/infra/\nmemory_keeper, monitor, calendar, knowledge_updater"]
    end

    subgraph TS["TypeScript  (browser only)"]
        B["agents/browser/server.ts\nExpress + Stagehand + Playwright\nport 3100"]
    end

    PY -->|aiohttp POST| TS
    TS -->|JSON response| PY
```

**Why this split:** Python has the best AI/agent libraries — LangGraph, Mem0, Qdrant client, temporalio. The TypeScript Stagehand v3 SDK is significantly ahead of the Python SDK for Browserbase automation. The two layers communicate via HTTP only and never share imports.

The rule: **Python calls TypeScript. TypeScript never calls Python.**

---

## Communication model

```mermaid
graph LR
    subgraph CHANNELS["Three communication channels"]
        PUB["Redis pub/sub\nagent:trigger\ncommander:*\nfigma:write\ncalendar:create_events"]
        KV["Redis key/value\nhackathon:{id}:*\ntask:{id}:{agent}\ncheckpoint:{id}:{type}"]
        HTTP["HTTP\nlocalhost:3100\nbrowser layer only"]
    end

    CMD["Commander"] -->|publish trigger| PUB
    PUB -->|subscribe| AGT["Agent workers"]
    AGT -->|set status| KV
    CMD -->|poll status| KV
    AGT -->|POST /scrape etc| HTTP
    HTTP -->|JSON| AGT
```

**No agent calls another agent directly.** All coordination goes through Redis. The Commander publishes triggers; workers consume them and update their status keys; the Commander polls those keys to know when to proceed.

---

## Crash recovery

```mermaid
sequenceDiagram
    participant C as Commander
    participant PG as PostgreSQL
    participant R as Redis
    participant W as Worker agents

    C->>PG: Checkpoint state (LangGraph)
    C->>R: Publish task trigger
    R->>W: Worker receives trigger
    W->>R: Set status: in-progress

    Note over C: Server crashes here

    C->>PG: Resume from last checkpoint
    C->>R: Check existing task status
    R->>C: status: in-progress (already running)
    Note over C: Skip re-triggering — worker still running

    W->>R: Set status: done
    C->>R: Poll — sees done
    C->>PG: Advance to next node
```

PostgreSQL checkpointing via LangGraph means the Commander survives crashes. Temporal provides workflow durability for long-running multi-day hackathons. Workers are stateless — they consume from Redis, complete their task, and update their status. If a worker dies mid-task, the Commander detects a stale `in-progress` after a timeout and retriggers.

---

## Key design decisions

| Decision | Rationale |
|---|---|
| Python primary, TS browser-only | Best AI libs in Python. Best browser automation in TS. HTTP bridge between them. |
| Redis pub/sub for agent coordination | Decoupled, debuggable, replay-friendly. No agent calls another directly. |
| SOP artifacts published to Redis immediately | Backend publishes `ApiContract` before full implementation — frontend unblocks and runs in parallel. |
| LangGraph + PostgreSQL checkpoints | Commander survives server crashes. State is durable, not in-memory. |
| UX Auditor has veto power | Prevents AI slop from reaching judges. Score < 7.0 or any anti-slop violation = blocked. |
| Knowledge Updater modifies `design_constitution.py` | Living knowledge (stacks, trends) updates automatically. Static laws never change. |
| Single ElectronHub gateway | One entry point for all LLM calls. Routing, fallback, cost tracking in one place. |
