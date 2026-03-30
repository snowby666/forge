# 10 — Hackathon Intelligence

How Forge evaluates opportunities, builds competitive concepts, and calibrates to specific judges. The intelligence layer is why Forge wins rather than just submitting.

---

## Opportunity scoring

```mermaid
graph TD
    SCRAPE["Browser layer scrapes\nDevpost, Lablab, Devfolio, MLH"]
    RAW["Raw hackathon listing\n{name, url, deadline, prizes, theme, description}"]
    SCORE["Scoring engine\nrule-based + LLM"]

    subgraph RUBRIC["Scoring rubric (100 points total)"]
        R1["Prize pool\nmax 25 pts\n$10k+=25, $5k+=15, $1k+=8, <$1k=0"]
        R2["Sponsor prizes\nmax 20 pts\n3+ separate prizes=20, 2=14, 1=7, 0=0"]
        R3["Deadline buffer\nmax 15 pts\n10+days=15, 5+days=10, 3+days=5, <3=0"]
        R4["Theme fit\nmax 20 pts\nLLM-scored: AI/automation/agents=20\ntech general=10, non-tech=0"]
        R5["Competition size\nmax 20 pts\n<100 teams=20, <300=10, 300+=5"]
    end

    RESULT{"Score >= 65?"}
    REGISTER["Register + schedule\ncalendar events"]
    SKIP["Skip — not worth it"]

    SCRAPE --> RAW --> SCORE
    SCORE --> R1 & R2 & R3 & R4 & R5
    R1 & R2 & R3 & R4 & R5 --> RESULT
    RESULT -->|yes| REGISTER
    RESULT -->|no| SKIP
```

**Why 65 as the threshold?** Below 65 typically means either the prize isn't worth the agent hours OR the theme doesn't align with what Forge builds well (multi-agent AI tools, developer automation). The LLM theme-fit score is the swing factor — a $500 hackathon with a perfect AI agent theme can still score 68.

---

## The 4-agent intelligence synthesis

```mermaid
graph LR
    subgraph IN["Inputs"]
        HB["HackathonBrief\n(from Scout)"]
    end

    subgraph PARALLEL["4 agents run simultaneously"]
        CA["Competitor Analyst\n-> CompReport\n\nWhat WON here before\nWhat FAILED\nWhat GAP exists"]
        JP["Judge Profiler\n-> JudgeProfile\n\nWho are these judges\nWhat do they care about\nHow technical are they"]
        SR["Sponsor Researcher\n-> SponsorMap\n\nWhich sponsors have prizes\nHow complex is each API\nPrize ÷ hours = value score"]
    end

    subgraph OUT["Strategy Director synthesizes all 4"]
        SD["3 ranked concepts\nEach scored:\n- Win probability (40%)\n- Feasibility (30%)\n- Sponsor prize potential (30%)"]
    end

    HB --> CA & JP & SR
    CA & JP & SR --> SD
    HB --> SD
```

The Strategy Director is the only agent that sees all 4 reports simultaneously. It's designed to find intersections: a concept that fits the identified gap in past winners, that will resonate with the specific judge panel, and that naturally integrates the highest-value sponsor APIs.

---

## Competitor analysis methodology

```mermaid
flowchart TD
    SCRAPE["Scrape past winners\nfrom hackathon page"]
    SIMILAR["Search Qdrant for similar\npast hackathon winners\nwe've analyzed before"]

    subgraph ANALYSIS["Analysis dimensions"]
        A1["Problem categories\nWhat domains won?"]
        A2["Tech stack patterns\nWhat stack won?"]
        A3["Demo quality\nHigh/medium/low\npresentation quality of winners"]
        A4["Overused themes\nWhat's been done 5+ times\nin this category?"]
        A5["Gaps\nWhat problem type\nhasn't been tried?"]
    end

    POSITION["Positioning recommendation\n'Our project should be unique by ___'"]

    SCRAPE & SIMILAR --> ANALYSIS
    ANALYSIS --> POSITION
```

**Why past winners matter:** Hackathons repeat. Devpost's AI Innovation track has 3 years of data. Judges who've seen "AI customer support chatbot" 20 times will respond differently to "AI that closes purchase order holds in SAP without human intervention." The CompReport explicitly finds and names the gap.

---

## Judge profiling methodology

```mermaid
graph TD
    PAGE["Hackathon page\njudges section"]
    PROFILE["For each judge:\nLinkedIn, GitHub, Twitter/X\npast hackathon judging\npublic commentary"]

    subgraph DIMENSIONS["Profile dimensions"]
        D1["Background type\nengineering | design | product | VC | domain expert"]
        D2["Technical depth\nhigh | medium | low\n(will they review code?)"]
        D3["Known interests\nwhat do they talk about publicly?"]
        D4["Past judging\nwhat have they rewarded before?"]
    end

    subgraph RECOMMENDATIONS["Output recommendations"]
        R1["Panel character\n'Mostly senior engineers\n+ 2 VCs, low design background'"]
        R2["Language level\ntechnical | business | balanced"]
        R3["Demo depth\nhow technical should the README be?"]
        R4["Narrative framing\n'Focus on ROI metrics,\nnot architecture beauty'"]
    end

    PAGE --> PROFILE --> DIMENSIONS --> RECOMMENDATIONS
```

**Why this matters for design:** A panel of 4 engineers + 1 VC should see a dense `developer_tool` aesthetic. A panel of 2 VCs + 2 product managers + 1 engineer should see a clean `enterprise_workflow` aesthetic with business metrics prominent. The UI/UX Designer reads `JudgeProfile` before selecting a design personality.

---

## Concept scoring formula

```mermaid
graph LR
    WP["Win Probability\n0-40 points\n\nJudge alignment (15)\nPast winner differentiation (15)\nDemo clarity (10)"]
    FE["Feasibility\n0-30 points\n\nBuild time vs available (15)\nKnown failure modes (10)\nTeam capability (5)"]
    SP["Sponsor Prize Potential\n0-30 points\n\nTotal eligible prize value (15)\nEligibility confidence (10)\nIntegration complexity (5)"]

    TOTAL["Total score\nWP×0.4 + FE×0.3 + SP×0.3\n0-100"]

    WP & FE & SP --> TOTAL
```

**Sponsor prize potential formula:**
```
value_score = prize_amount × eligibility_confidence ÷ integration_hours

eligibility_confidence: 1.0 (high) | 0.7 (medium) | 0.4 (low)
```

A $3,000 prize that takes 2 hours with high confidence scores 1,500. A $5,000 prize that takes 8 hours with medium confidence scores only 437. The Integration Engineer builds in value_score order.

---

## What wins vs what loses

Derived from real hackathon outcomes stored in Mem0:

```mermaid
graph TD
    subgraph WIN["OK: Winning patterns"]
        W1["Agents that CLOSE LOOPS\nread system A -> decide -> write system B\nComposio pattern"]
        W2["Non-technical users + technical systems\n+ safety guardrails\nBridges skill gap with visible safety"]
        W3["Domain-specific with quantified impact\n'47% faster PO resolution'\nnot 'improves workflow efficiency'"]
        W4["Multi-system integration as the demo\nShows real complexity, not just a chatbot"]
        W5["Transparent agent reasoning\nShow the plan, the tool calls, the steps\nComposio execution log UI"]
    end

    subgraph LOSE["FAIL: Losing patterns"]
        L1["Generic chatbot + document upload\n500 other teams built this"]
        L2["RAG over PDFs\nwithout a specific, compelling use case"]
        L3["Another AI writing assistant\nGrammarly, Notion AI exist"]
        L4["'Personal AI companion'\nno specific domain focus"]
        L5["Social media automation\njudges don't find this impressive"]
    end
```

These patterns are stored in `LIVING_KNOWLEDGE["winning_concept_patterns_2026"]` and updated by the Knowledge Updater before each hackathon cycle.

---

## Concept red flags (auto-penalized by Strategy Director)

```python
CONCEPT_RED_FLAGS = [
    "name ends in 'AI' or 'GPT'",
    # → SupportAI, AnalysisGPT signal generic thinking

    "first sentence includes 'leveraging the power of AI'",
    # → Marketing speak, not product thinking

    "demo requires account creation to see value",
    # → Judges won't wait; first 30 seconds matter

    "core feature is 'summarize documents' or 'answer questions about data'",
    # → Commoditized by ChatGPT; not a differentiator

    "more than 4 features listed in description",
    # → Signals lack of focus; judges prefer depth over breadth

    "demo video starts with slides before showing product",
    # → Judges fast-forward to the product; start there
]
```

---

## The specificity test

The Strategy Director applies this test to every concept before scoring it:

```
GENERIC (loses): "An AI agent that helps businesses optimize their customer service workflows"

SPECIFIC (wins):  "Sarah is a customer support team lead at a 50-person B2B SaaS company.
                  She manages 8 agents handling 200 tickets/day. 23% of tickets that come in
                  after 5pm go unresolved until the next morning, causing churn.
                  Our agent monitors the ticket queue in real-time, classifies urgency with
                  domain-specific logic, pages the right on-call person via PagerDuty, and
                  drafts a first response — all within 4 minutes."
```

The specific version names: who Sarah is, the exact metric (23%), what time (after 5pm), the specific system (PagerDuty), and the specific outcome (4 minutes). This level of specificity:
1. Shows the team understands the actual problem
2. Gives judges a person to empathize with
3. Makes the demo obvious: show Sarah's ticket queue, trigger an after-hours ticket, watch the agent respond

---

## Sponsor integration strategy

```mermaid
flowchart TD
    SM["SponsorMap\nAll available prizes"]
    FILTER["Filter:\nIntegration hours <= 4h total\nNatural to the product"]
    RANK["Rank by value_score\n= prize × confidence ÷ hours"]
    SELECT["Select top 2-3\nThat are visible in the UI"]
    BUILD["Integration Engineer\nbuilds in priority order"]
    MANIFEST["SponsorIntegrationManifest\nList of qualified prize categories"]
    SUBMIT["Submission Agent\nchecks all prize checkboxes"]

    SM --> FILTER --> RANK --> SELECT --> BUILD --> MANIFEST --> SUBMIT
```

**The visibility rule:** Every integration must be visible in the product UI — a badge, a feature, a "Powered by X" attribution. Judges open the submission and scroll through the tech stack. If they can't see the sponsor's tech being used, the integration doesn't land.

**The naturalness rule:** Integrations that require rearchitecting the core product are not worth it. The best integrations are additive layers — the product works without them, but they make it meaningfully better and visibly display the sponsor's value.
