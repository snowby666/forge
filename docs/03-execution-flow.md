# 03 — Execution Flow

A complete 24-hour hackathon run from `forge scout` to `SubmissionURL`. Maps every phase, parallel track, human checkpoint, and dependency.

---

## Full lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Human
    participant CMD as Commander
    participant L1 as Intelligence layer
    participant L2 as Strategy layer
    participant L3 as Build layer
    participant L4 as Verify layer
    participant L5 as Polish layer
    participant L6 as Submission layer
    participant DB as Redis / PostgreSQL

    Note over CMD,DB: forge scout runs first (daily cron or manual)

    CMD->>L1: Trigger all 4 agents in parallel
    par Intelligence runs simultaneously
        L1->>DB: Publish HackathonBrief
        L1->>DB: Publish CompReport
        L1->>DB: Publish JudgeProfile
        L1->>DB: Publish SponsorMap
    end

    CMD->>CMD: Generate concepts (Strategy Director)
    CMD-->>Human: Slack: "3 concepts ready — pick one"
    Note over Human: Checkpoint 1: Concept pick (~15 min)
    Human-->>CMD: forge approve concept

    par Strategy runs simultaneously
        CMD->>L2: Trigger PM
        CMD->>L2: Trigger Tech Architect
    end
    L2->>DB: Publish ApiContract <- immediately on schema design
    Note over DB: Frontend unblocks here, not when backend is done

    CMD-->>Human: Slack: "Design ready for review"
    Note over Human: Checkpoint 2: Design approve (~10 min)
    Human-->>CMD: forge approve design

    par Build runs simultaneously
        CMD->>L3: Frontend Engineer (waits for ApiContract event)
        CMD->>L3: Backend Engineer
        CMD->>L3: Integration Engineer
        CMD->>L3: Test Engineer
        CMD->>L3: DevOps
        CMD->>L3: Security Agent
    end

    par Verification runs continuously
        CMD->>L4: Code Reviewer
        CMD->>L4: UX Auditor [veto]
        CMD->>L4: Performance Agent
    end

    L4-->>CMD: UXAuditReport (approved or blocked)
    alt UX Auditor blocks
        CMD->>L5: Polish Agent (targeted fixes)
        CMD->>L4: Re-audit
    end

    CMD-->>Human: Slack: "Preview URL ready"
    Note over Human: Checkpoint 3: Quality review (~20 min)
    Human-->>CMD: forge approve quality

    par Polish runs simultaneously
        CMD->>L5: Polish Agent
        CMD->>L5: Copy Writer
        CMD->>L5: Data Seeder
        CMD->>L5: Brand Agent
    end

    par Submission prep runs simultaneously
        CMD->>L6: Demo Producer
        CMD->>L6: Pitch Writer
    end

    CMD-->>Human: Slack: "All materials ready — final review"
    Note over Human: Checkpoint 4: Submit approve (~10 min)
    Human-->>CMD: forge approve submit

    CMD->>L6: Submission Agent
    L6->>DB: Publish SubmissionURL
    CMD-->>Human: "Submitted ✓"

    Note over CMD,DB: 36 hours after deadline
    CMD->>L7: Trigger Outcome Tracker
    L7->>DB: Scrape placement + feedback
    L7->>DB: store_outcome() — memory loop closed
    L7->>DB: Feed signal to LIVING_KNOWLEDGE
```

---

## Parallel execution map

```mermaid
gantt
    title Forge execution timeline (24h hackathon)
    dateFormat HH:mm
    axisFormat %H:%M

    section Intelligence
    Scout + register          :done, 00:00, 01:00
    Competitor Analyst        :done, 00:00, 01:00
    Judge Profiler            :done, 00:00, 01:00
    Sponsor Researcher        :done, 00:00, 01:00

    section Checkpoint 1
    Human: concept pick       :crit, 01:00, 01:15

    section Strategy
    Strategy Director         :done, 01:15, 01:45
    PM                        :done, 01:45, 02:30
    Tech Architect            :done, 01:45, 02:30

    section Checkpoint 2
    Human: design approve     :crit, 02:30, 02:40

    section Design
    UI/UX Designer            :done, 02:40, 05:30

    section Build (parallel)
    Frontend Engineer         :active, 05:30, 15:30
    Backend Engineer          :active, 02:40, 10:30
    Integration Engineer      :active, 05:30, 11:30
    Test Engineer             :active, 05:30, 11:30
    DevOps                    :active, 05:30, 07:30
    Security Agent            :active, 13:30, 14:30

    section Verify (continuous)
    Code Reviewer             :active, 05:30, 15:30
    UX Auditor                :active, 05:30, 15:30
    Performance Agent         :active, 05:30, 15:30

    section Checkpoint 3
    Human: quality review     :crit, 15:30, 16:00

    section Polish (parallel)
    Polish Agent              :done, 16:00, 18:00
    Copy Writer               :done, 16:00, 17:00
    Data Seeder               :done, 16:00, 17:00
    Brand Agent               :done, 16:00, 17:00

    section Submission prep (parallel)
    Demo Producer             :done, 16:00, 18:00
    Pitch Writer              :done, 16:00, 17:00

    section Checkpoint 4
    Human: submit approve     :crit, 18:00, 18:10

    section Submit
    Submission Agent          :done, 18:10, 18:40
```

---

## Commander state machine

```mermaid
stateDiagram-v2
    [*] --> run_intelligence: forge run --id X

    run_intelligence --> generate_concepts: all 4 intel agents done

    generate_concepts --> wait_concept_approval: concepts published to Redis\nSlack notified

    wait_concept_approval --> run_planning: human approved\n(or timeout -> auto-select)
    wait_concept_approval --> [*]: errors in intel phase

    run_planning --> run_design: PM + Architect done\nApiContract published

    run_design --> wait_design_approval: DESIGN.md ready\nSlack notified

    wait_design_approval --> run_build: human approved

    run_build --> run_verification: Frontend done\n(Backend may still run)
    run_build --> [*]: frontend failed after 3 attempts

    run_verification --> wait_quality_review: UX Auditor score >= 7.0\nSlack notified

    run_verification --> run_build: UX Auditor blocked\nretrigger with fix instructions

    wait_quality_review --> run_polish: human approved

    run_polish --> run_submission: all 4 polish agents done

    run_submission --> schedule_outcome: SubmissionURL published
    schedule_outcome --> [*]: Outcome Tracker scheduled\n(fires 36h after deadline)
```

---

## The critical dependency: ApiContract

```mermaid
sequenceDiagram
    participant BE as Backend Engineer
    participant RD as Redis
    participant FE as Frontend Engineer

    Note over BE: Starts immediately after design approval
    BE->>BE: Design schema (30 min)
    BE->>RD: SET hackathon:{id}:api_contract
    BE->>RD: PUBLISH agent:api_contract_ready

    Note over FE: Was waiting, now unblocks
    RD-->>FE: Receives api_contract_ready event
    FE->>FE: Start generating pages with API calls

    Note over BE: Backend continues implementation (6-8 more hours)
    BE->>BE: Implement endpoints
    BE->>BE: Run pytest
    BE->>BE: Deploy to Railway
```

**Why this matters:** The frontend can generate type-safe API call code immediately from the contract, without waiting for backend implementation. This compresses the critical path by hours on a 24-hour hackathon.

---

## UX Audit decision tree

```mermaid
flowchart TD
    BUILD_DONE["Build layer done\nPreviewURL available"]
    AUDIT["UX Auditor\nbrowses PreviewURL\nscreenshots 375px + 1440px\nruns Lighthouse"]
    SLOP{"Any anti-slop\nviolation?"}
    SCORE{"Score >= 7.0\n(weighted avg)?"}
    LIGHTHOUSE{"Lighthouse\nAccessibility >= 85?"}
    APPROVED["OK: UXAuditReport: approved\nCommander continues to Checkpoint 3"]
    BLOCK1["FAIL: BLOCKED\nIssue fix instructions\nto Polish Agent"]
    POLISH_FIX["Polish Agent applies\nspecific targeted fixes"]
    REAUDIT["Re-audit\n(second attempt)"]
    FINAL{"Final score?"}
    ESCALATE["Escalate to human\nSlack: 'Design issues'"]

    BUILD_DONE --> AUDIT
    AUDIT --> SLOP
    SLOP -->|yes| BLOCK1
    SLOP -->|no| SCORE
    SCORE -->|< 7.0| BLOCK1
    SCORE -->|>= 7.0| LIGHTHOUSE
    LIGHTHOUSE -->|< 85| BLOCK1
    LIGHTHOUSE -->|>= 85| APPROVED
    BLOCK1 --> POLISH_FIX
    POLISH_FIX --> REAUDIT
    REAUDIT --> FINAL
    FINAL -->|approved| APPROVED
    FINAL -->|still blocked| ESCALATE
```

---

## Human checkpoint details

| Checkpoint | Trigger | Timeout | Auto-fallback | What you see |
|---|---|---|---|---|
| **concept_approval** | After Strategy Director | 24h | Auto-selects recommended concept | 3 concepts with scores, rationale, win-probability |
| **design_approval** | After UI/UX Designer | 8h | Proceeds with current design | DESIGN.md link, Figma URL, self-critique score |
| **quality_review** | After UX Auditor passes | 4h | Proceeds to polish | Live Vercel URL, audit score, Lighthouse scores |
| **submission_approval** | After Demo + Pitch done | 2h | Does NOT auto-submit | Preview URL, video URL, description preview, Devpost form dry-run screenshot |

> Note: submission_approval never auto-submits regardless of timeout. It requires explicit human confirmation.

---

## SOP artifact dependency graph

```mermaid
graph LR
    HB["HackathonBrief"]
    CR["CompReport"]
    JP["JudgeProfile"]
    SM["SponsorMap"]

    HB --> CR
    HB --> JP
    HB --> SM

    CB["ConceptBrief"]
    CR & JP & SM & HB --> CB

    PP["ProjectPlan"]
    CB & HB & JP --> PP

    DB["DbSchema"]
    AC["ApiContract !"]
    DG["DependencyGraph"]
    PP --> DB & AC & DG

    DS_spec["DesignSpec"]
    DT["DesignTokens"]
    CS["ComponentSpecs"]
    DM["DESIGN_MD"]
    PP & JP & HB --> DS_spec & DT & CS & DM

    FA["FrontendApp"]
    BA["BackendAPI"]
    SP["SponsorPlugins"]
    DS_spec & DT & CS & DM & AC --> FA
    PP & DB --> BA
    SM & PP & AC --> SP

    PU["PreviewURL"]
    FA --> PU

    UA["UXAuditReport"]
    PU & DS_spec & DM --> UA

    PA["PolishedApp"]
    FA & UA & DS_spec --> PA

    SD_data["SeedData"]
    BK["BrandKit"]
    PP & AC & BA --> SD_data
    DS_spec & DT & PP --> BK

    SIM["SponsorIntegrationManifest"]
    SP --> SIM

    DV["DemoVideo"]
    RD["README"]
    PD["PitchDeck"]
    SD_desc["SubmissionDescription"]
    PA & PP --> DV
    PP & JP & SIM --> RD & PD & SD_desc

    SU["SubmissionURL"]
    PA & DV & RD & PD & SD_desc & SIM --> SU
```

`⚡` = published immediately by Architect, does not wait for implementation
