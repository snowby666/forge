# 05 — Design Constitution

The design brain of Forge. Everything UI-related flows through `config/design_constitution.py`. It has two parts: a **frozen section** that encodes timeless design principles, and a **living section** that agents update via web research.

---

## File structure

```mermaid
graph TD
    subgraph FROZEN["🔒 Frozen — never modified by agents"]
        RS["REFERENCE_SITES\nComposio, Hex, Riff, Linear, Vercel\nThe real standard"]
        SDL["STATIC_DESIGN_LAWS\n7 timeless laws\nData density, code as content,\nstatus visibility, precision palette,\ntypography, components, 30-sec rule"]
        ASR["ANTI_SLOP_RULES\n38 specific patterns\nto block and avoid"]
        DP["DESIGN_PERSONALITIES\n5 named aesthetics:\ndeveloper_tool, data_tool,\nenterprise_workflow,\nai_agent_realtime, consumer_product"]
        DCR["DESIGN_CRITIQUE_RUBRIC\n6 scored dimensions\nweighted average >= 7.0"]
        CQC["COMPONENT_QUALITY_CHECKLIST\n4 categories:\ninteractive states, copy,\naccessibility, performance"]
        DT["class DesignTokens\nDTCG-compliant token structure"]
        SP["SYSTEM_PROMPT_DESIGN_AGENT\nSYSTEM_PROMPT_FRONTEND_AGENT\nSYSTEM_PROMPT_STRATEGY_AGENT"]
    end

    subgraph LIVING["🔄 Living — updated by Knowledge Updater"]
        LK["LIVING_KNOWLEDGE dict\n- trending_component_libraries\n- winning_aesthetic_2026\n- winning_concept_patterns_2026\n- frontend_stack_2026\n- backend_stack_2026"]
    end

    subgraph BOUNDARY["Boundary markers"]
        START["# KNOWLEDGE_UPDATER_SECTION_START"]
        END["# KNOWLEDGE_UPDATER_SECTION_END"]
    end

    START --> LK --> END
```

---

## The reference standard

Forge's design agents are calibrated to specific real companies — not abstract principles.

```mermaid
graph LR
    subgraph composio["composio.dev"]
        C1["Dense terminal aesthetic"]
        C2["Code blocks as primary UI"]
        C3["Tool badges inline"]
        C4["Execution logs as content"]
        C5["bg: #0a0a0a, accent: #22c55e"]
    end

    subgraph hex["hex.tech"]
        H1["Data notebook aesthetic"]
        H2["32px row heights in tables"]
        H3["Monospace for data cells"]
        H4["Density = luxury"]
        H5["bg: #0f1117, accent: #8b5cf6"]
    end

    subgraph riff["riff.ai"]
        R1["Enterprise workflow tool"]
        R2["Numbered steps as nav"]
        R3["Status pills everywhere"]
        R4["Show the work, not magic"]
        R5["bg: #ffffff, accent: #3b82f6"]
    end

    subgraph linear["linear.app"]
        L1["Keyboard-first"]
        L2["Ultra-dark, one accent"]
        L3["40px row heights"]
        L4["bg: #0f0f0f, accent: #5e6ad2"]
    end
```

**The test:** Does this look like it belongs on one of these sites? If not, the UX Auditor blocks it.

---

## The 5 design personalities

```mermaid
graph TD
    QUESTION["What is the target user?"]
    QUESTION --> DEV{"Developer\nusing APIs, code,\nlogs, technical config?"}
    QUESTION --> DATA{"Analyst or data\nscientist surfacing data?"}
    QUESTION --> ENT{"Business operator\nwith approval flows\nand integrations?"}
    QUESTION --> AI{"Real-time AI output\nagent thinking visible?"}
    QUESTION --> CON{"Non-technical user\nproductivity/personal?"}

    DEV -->|yes| DT["developer_tool\nRef: Composio, Linear\nbg: #09090b, accent: #22c55e\nGeist Sans + Geist Mono\n13px base, 36px rows"]
    DATA -->|yes| DTA["data_tool\nRef: Hex, Grafana\nbg: #0f1117, accent: #8b5cf6\nInter + JetBrains Mono\n13px base, 32px rows"]
    ENT -->|yes| EW["enterprise_workflow\nRef: Riff, Notion Enterprise\nbg: #ffffff, accent: #3b82f6\nInter + Roboto Mono\n14px base, 48px rows"]
    AI -->|yes| AIR["ai_agent_realtime\nRef: Claude.ai, Cursor\nbg: #1a1a1a, accent: #a78bfa\nGeist Sans + Geist Mono\n14px base, auto rows"]
    CON -->|yes| CP["consumer_product\nRef: Loom, Figma\nbg: #fafaf9, accent: #f97316\nInter + Fira Code\n15px base, 52px rows"]
```

---

## The 7 static design laws

```mermaid
mindmap
  root((7 Design Laws))
    Law 1
      Data density over decorative whitespace
      32-40px row heights not 56-64px
      Dense tools respect user time
    Law 2
      Code is content
      Monospace text is first-class UI
      Syntax highlighting required
    Law 3
      Status is always visible
      Green dot, checkmark, red x
      Inline not modal
    Law 4
      Precision palette
      One accent color maximum
      Near-blacks not pure black
    Law 5
      Typography as hierarchy signal
      One typeface only
      6 sizes only, 3 weights only
    Law 6
      Components encode meaning
      Primary button for ONE action
      Semantic color only
    Law 7
      The 30-second rule
      Wow number is largest element
      Demo starts in action
```

---

## Anti-slop categories

```mermaid
pie title 38 anti-slop rules by category
    "Layout crimes" : 8
    "Color crimes" : 6
    "Typography crimes" : 6
    "Component crimes" : 6
    "Copy crimes" : 8
    "Interaction crimes" : 4
```

**The highest-priority rules** (UX Auditor auto-blocks on these):

| # | Rule | Why it matters |
|---|---|---|
| 1 | Centered hero + tagline + gradient background | Most common AI slop output in 2026 |
| 3 | Three-column emoji feature grid | Signals "I used a template" |
| 8 | Blue-purple gradient as brand color | Peak AI slop indicator |
| 9 | Glassmorphism as primary aesthetic | Outdated by 2024, still everywhere |
| 27 | "Revolutionize your workflow" in any headline | Judges have read this 500 times |
| 31 | Empty state: just "No items found" | No recovery path = bad UX |

---

## UX Audit scoring

```mermaid
graph LR
    subgraph DIMS["6 scored dimensions"]
        D1["Reference site match\nweight: 2.0×\nMax: 20 pts"]
        D2["Data density\nweight: 1.5×\nMax: 15 pts"]
        D3["Status visibility\nweight: 1.5×\nMax: 15 pts"]
        D4["Visual hierarchy\nweight: 1.5×\nMax: 15 pts"]
        D5["Interaction quality\nweight: 1.0×\nMax: 10 pts"]
        D6["Demo path clarity\nweight: 2.0×\nMax: 20 pts"]
    end

    subgraph GATES["Gates"]
        G1["Weighted avg >= 7.0"]
        G2["No anti-slop violations\n(auto-block regardless of score)"]
        G3["Lighthouse Accessibility >= 85"]
    end

    D1 & D2 & D3 & D4 & D5 & D6 --> CALC["(sum × weights) / 8.5\n= overall score"]
    CALC --> G1
    G1 & G2 & G3 --> RESULT{"All pass?"}
    RESULT -->|yes| APPROVE["OK: Approved"]
    RESULT -->|no| BLOCK["FAIL: Blocked\nFix instructions issued"]
```

---

## The living knowledge system

```mermaid
sequenceDiagram
    participant CMD as Commander
    participant KU as Knowledge Updater
    participant EH as ElectronHub
    participant DC as design_constitution.py

    CMD->>KU: Run before each hackathon cycle
    par 5 research tasks in parallel
        KU->>EH: Research trending libraries
        KU->>EH: Research winning concepts
        KU->>EH: Research winning aesthetic
        KU->>EH: Research frontend stack
        KU->>EH: Research backend stack
    end
    EH-->>KU: Research results (Pydantic models)
    KU->>DC: Read current LIVING_KNOWLEDGE
    KU->>KU: Merge new + current (fallback on failure)
    KU->>KU: ast.parse() validation
    KU->>KU: Verify all frozen sections intact
    KU->>DC: Backup original (.py.bak)
    KU->>DC: Write new LIVING_KNOWLEDGE section only
    KU-->>CMD: Update complete: {date, sections}
```

**Validation before write:** The updater parses the updated file as Python AST. If it has a syntax error, it refuses to write. It also verifies all 8 frozen section markers are still present. If any check fails, the backup is preserved and an error is raised.

---

## Design token structure (DTCG)

```mermaid
graph TD
    subgraph PRIMITIVE["Primitive layer\nnever use directly in components"]
        P1["color_black: #09090b"]
        P2["color_white: #fafafa"]
    end

    subgraph SEMANTIC["Semantic layer\nuse these in components"]
        S1["color_bg_base\ncolor_bg_surface\ncolor_bg_raised"]
        S2["color_text_primary\ncolor_text_secondary\ncolor_text_muted"]
        S3["color_accent\ncolor_accent_muted"]
        S4["color_success: #22c55e\ncolor_warning: #f59e0b\ncolor_error: #ef4444\ncolor_running: #8b5cf6"]
    end

    subgraph COMPONENT["Component layer\nspecific to elements"]
        C1["row_height_compact: 32px\nrow_height_default: 40px"]
        C2["header_height: 48px\nsidebar_width: 240px"]
        C3["duration_fast: 120ms\neasing: cubic-bezier(0.16,1,0.3,1)"]
    end

    PRIMITIVE --> SEMANTIC --> COMPONENT
```

The personality selection fills the semantic layer. Agents always reference tokens, never hardcoded hex values.

---

## Component quality gates

Every component must pass all items before it is considered done:

```mermaid
graph TD
    COMP["Component generated"]
    COMP --> STATES{"All 8 states?"}
    STATES --> S1["Default\nHover (bg-color, not opacity)\nFocus (2px ring)\nActive (scale 0.97)\nDisabled (40% opacity)\nLoading (shape-matched skeleton)\nError (specific message)\nEmpty (SVG + copy + CTA)"]
    COMP --> COPY{"Real copy?"}
    COPY --> C1["No lorem ipsum\nNumbers formatted: 1,234\nDates relative: '2h ago'\nErrors: what + how to fix"]
    COMP --> A11Y{"Accessibility?"}
    A11Y --> A1["Contrast >= 4.5:1\nNon-color status indicators\nTap targets >= 40×40px\naria-label on icon-only buttons"]
    COMP --> PERF{"Performance?"}
    PERF --> P1["No animations on >10 repeated elements\nTransitions: transform/opacity only\nImages: explicit width/height"]

    S1 & C1 & A1 & P1 --> DONE["OK: Component done"]
```
