"""
Design Constitution v3
======================
The real standard: Composio, Hex, Riff, Linear, Vercel, Raycast.

NOT: Notion clones. NOT: generic SaaS blue gradients. NOT: chatbot bubbles.
NOT: marketing sites pretending to be apps.

This file has two parts:
  1. STATIC CONSTITUTION — the timeless principles from the reference sites.
     Do NOT change these. They encode what $100M+ design teams figured out.

  2. LIVING KNOWLEDGE SYSTEM — updated by the Knowledge Updater agent via web search.
     These sections ARE changed by agents when trends shift.

The UI/UX Designer agent reads this file at runtime before generating anything.
The UX Auditor scores against this file's rubric.
The Frontend Engineer follows this file's component patterns.
"""

KNOWLEDGE_VERSION = "3.0.0"  # bumped by knowledge_updater agent

REFERENCE_SITES = {
    "composio.dev": {
        "aesthetic": "Dense developer terminal. Code blocks as primary UI element. Tool badges inline. Status as structured text not icons.",
        "palette": "Very dark (#0a0a0a, #111, #1a1a1a), pure white text (#f5f5f5), precise single accent (lime green #22c55e or electric blue)",
        "typography": "Geist Mono for code/status. Geist Sans for labels. Tight line height (1.3). Small font (12-13px) is fine for dense data.",
        "spacing": "Extremely tight. 4px between related items. 8px between groups. 16px between sections. NO 64px hero padding.",
        "components": "Inline tool badges (16x16 icon + name). Execution plan as numbered list. Warning/error as inline pills. Code as actual code blocks.",
        "anti_patterns": ["hero sections", "gradient backgrounds", "marketing copy as UI", "large icons", "centered layouts"],
        "key_insight": "The PRODUCT is the design. The data and execution state are what users read, not decorative chrome.",
    },
    "hex.tech": {
        "aesthetic": "Data notebook. Information density is the premium feature. Tables are first-class citizens. Tabs for mode switching.",
        "palette": "Dark navy (#0f1117, #161b22) background. Off-white (#e6edf3) text. Purple accent (#8b5cf6) for AI features. Semantic green/red for data status.",
        "typography": "Inter for UI chrome. Monospace for data cells, SQL, code output. 13px base for data, 14px for labels.",
        "spacing": "32px row heights for data tables (not 56px). Compact nav. Dense sidebars. Data fills the screen.",
        "components": "SQL editor with syntax highlighting. Output tables with alternating row colors. Inline stats in table headers. Tab bars that look like tabs, not pills.",
        "anti_patterns": ["cards for everything", "empty dashboard states that are 'beautiful'", "charts with too much whitespace", "oversized chart titles"],
        "key_insight": "Analysts don't want beauty. They want to see more data. Density = respect for the user's time.",
    },
    "riff.ai": {
        "aesthetic": "Enterprise workflow builder. Form fields as the hero. Status pills everywhere. Serious tool for serious business.",
        "palette": "Clean white (#ffffff, #f6f9fc) for light mode. Near-black (#1a1f36) text. Electric blue (#3b82f6) CTAs only. Red/amber/green status only where earned.",
        "typography": "Inter. 14px body. 16px labels. 24px section headers max. Weight 500 for anything interactive.",
        "spacing": "16px between form fields. 24px between sections. Generous padding on cards but NOT on data tables.",
        "components": "Multi-step numbered workflows as the primary nav metaphor. Integration logos as trust signals. Workflow steps as vertical timeline.",
        "anti_patterns": ["abstract icons for workflow steps", "hiding complexity with 'AI magic'", "fake chat interfaces"],
        "key_insight": "Enterprise trust comes from showing the work. Show the data flow, the integration points, the audit trail.",
    },
    "linear.app": {
        "aesthetic": "Keyboard-first product tool. Everything accessible via cmd+K. Ultra-dark, high contrast, precise.",
        "palette": "#0f0f0f base, #1c1c1c surface, #2a2a2a raised, white text, one purple accent (#5e6ad2)",
        "spacing": "8px base grid, religiously. 40px row height for list items.",
        "key_insight": "Speed is a feature. Every interaction must feel instant.",
    },
    "vercel.com": {
        "aesthetic": "Pure black and white. Brand IS the restraint. Color ONLY for semantic meaning.",
        "palette": "#000000 base. #ffffff text. #111111 cards. #333333 borders. Zero decorative color.",
        "key_insight": "Maximum contrast. Minimum color. The work speaks. The chrome whispers.",
    },
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATIC DESIGN LAWS — DO NOT MODIFY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATIC_DESIGN_LAWS = """
## THE REFERENCE STANDARD
Does this look like it belongs on composio.dev, hex.tech, or linear.app?
NOT: does this look like a Notion template or generic SaaS landing page?

## LAW 1: DATA DENSITY OVER DECORATIVE WHITESPACE
Information density is the luxury feature in developer/data tools.
- Row heights: 32-40px for data tables (NOT 56-64px)
- Use 4px and 8px spacing between related items. 24-32px for section breaks.
- Empty space is expensive in a tool. Fill it with useful data.

## LAW 2: CODE IS CONTENT
In 2026 developer tools, monospace text and code blocks ARE the primary design element.
- Composio's hero shows a terminal and code block — that IS the product demo
- Hex shows SQL cells and data tables — that IS the value prop
- Code blocks must be syntax-highlighted. Status output must look like real terminal output.

## LAW 3: STATUS IS ALWAYS VISIBLE
- Every async operation has a visible status badge
- Status: green dot = running, checkmark = done, red x = failed
- Show: what is happening, which step, progress percentage
- Inline status, not modal popups

## LAW 4: PRECISION PALETTE
- One brand accent MAXIMUM. Only on primary actions.
- No gradients except semantic ones (success pulse, etc.)
- Near-black backgrounds: #09090b, #0a0a0a, #0f0f0f, #111111
- Near-white text on dark: #f4f4f5, #ededed, #e4e4e7 — NEVER pure #ffffff
- Muted text: exactly 40-50% opacity of primary text

## LAW 5: TYPOGRAPHY AS HIERARCHY SIGNAL
- ONE typeface. Geist or Inter. Monospace variant for data/code.
- Size scale: 11/12/13/14/16/18/24/32px — NO other sizes
- Weight scale: 400/500/600 — NO 700 or 800 in tool UIs
- Monospace for: code, IDs, timestamps, numbers in tables, status codes

## LAW 6: COMPONENTS ENCODE MEANING
- Buttons: ONLY primary (brand) for the ONE most important action per screen
- Badges/pills: semantic ONLY (green=success, red=error, amber=warning, purple=AI running)
- Icons: Lucide React, 16px inline, 20px buttons, 24px illustrations
- Borders: 1px, 0.5px opacity — not decorative, only for grouping

## LAW 7: THE 30-SECOND RULE
Design for the 30 seconds a judge has before deciding.
- Primary metric or "wow number" = largest element on main screen
- Demo starts already in action — not at login or empty state
- AI doing something = first interaction possible
- Realistic data > beautiful empty states
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ANTI-SLOP RULES — DO NOT MODIFY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ANTI_SLOP_RULES = """
## ANTI-SLOP RULES (UX Auditor auto-blocks on ANY violation)

### Layout crimes
1. Centered hero + large headline + subtitle + 2 CTA buttons + background image
2. Three-column features grid with emoji icons
3. Testimonial section with circular avatar photos and star ratings
4. Pricing table with "Most Popular" badge in the middle column
5. Dashboard where EVERY metric is in its own card with an icon
6. Sidebar with 8+ items at the same visual weight
7. Modal for non-destructive confirmation

### Color crimes
8. Blue-purple gradient as primary brand or background
9. Glassmorphism as the primary aesthetic
10. Neon/vivid accent >70% saturation on >5% of screen
11. Multiple accent colors without semantic mapping
12. Pure #000000 or #ffffff (use near-blacks/near-whites)
13. Text failing WCAG 4.5:1 contrast ratio

### Typography crimes
14. Bold text scattered through paragraph copy for "emphasis"
15. All-caps section labels everywhere (more than 3 instances)
16. Line height below 1.4 on body text
17. More than 2 different font weights on a single screen
18. Gradient text on headlines
19. Font size below 12px for any readable content

### Component crimes
20. Progress bars always at 67% (static default)
21. Spinning loaders for >3 seconds instead of skeleton
22. Notification bell in header that does nothing
23. Breadcrumbs on 2-level navigation
24. Avatar circles with RANDOM colors each render
25. "Powered by AI" badge that doesn't explain anything

### Copy crimes
26. "Revolutionize your workflow" or any headline with "revolutionize"
27. "AI-powered" as a feature name
28. Bullets starting with: Streamline / Optimize / Enhance / Leverage
29. CTAs saying "Get Started" on something requiring onboarding
30. Empty state: just "No items found" with no action
31. Error message: "Something went wrong" with no specifics
32. Loading: "Loading..." with no context
33. Success toast disappearing in <3 seconds

### Interaction crimes
34. Click target below 40x40px
35. Hover effect = only opacity change (use background-color change)
36. Form submit with no loading state on button
37. Input validation only on submit (validate on blur too)
38. Tooltip covering what it describes
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DESIGN PERSONALITIES — DO NOT MODIFY THE STRUCTURE, VALUES UPDATED BY AGENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DESIGN_PERSONALITIES = {
    "developer_tool": {
        "reference": "Composio, Linear, Raycast",
        "description": "Dense, terminal-native, data-forward. The product IS the data.",
        "bg_base": "#09090b",
        "bg_surface": "#111113",
        "bg_raised": "#18181b",
        "text_primary": "#fafafa",
        "text_secondary": "#a1a1aa",
        "text_tertiary": "#52525b",
        "border": "rgba(255,255,255,0.08)",
        "accent": "#22c55e",
        "font_sans": "Geist Sans",
        "font_mono": "Geist Mono",
        "base_size": "13px",
        "line_height": "1.35",
        "row_height": "36px",
        "anti_patterns": ["light mode default", "large hero", "marketing language"],
        "use_when": "Target user is a developer. Product involves code, APIs, logs, technical config.",
    },
    "data_tool": {
        "reference": "Hex, Grafana modern, Datadog",
        "description": "Notebook/analyst aesthetic. Tables are first-class. Dense is good.",
        "bg_base": "#0f1117",
        "bg_surface": "#161b22",
        "bg_raised": "#1c2128",
        "text_primary": "#e6edf3",
        "text_secondary": "#8d96a0",
        "text_tertiary": "#484f58",
        "border": "rgba(255,255,255,0.12)",
        "accent": "#8b5cf6",
        "font_sans": "Inter",
        "font_mono": "JetBrains Mono",
        "base_size": "13px",
        "line_height": "1.4",
        "row_height": "32px",
        "anti_patterns": ["empty state animations", "chart padding >8px", "table cells >40px"],
        "use_when": "Target user is analyst, data scientist, or ops. Product surfaces data.",
    },
    "enterprise_workflow": {
        "reference": "Riff, Notion, Coda (enterprise)",
        "description": "Serious workflow tool. Form fields as heroes. Status everywhere.",
        "bg_base": "#ffffff",
        "bg_surface": "#f6f9fc",
        "bg_raised": "#eef2f7",
        "text_primary": "#1a1f36",
        "text_secondary": "#697386",
        "text_tertiary": "#9fa9ba",
        "border": "#e3e8ef",
        "accent": "#3b82f6",
        "font_sans": "Inter",
        "font_mono": "Roboto Mono",
        "base_size": "14px",
        "line_height": "1.5",
        "row_height": "48px",
        "anti_patterns": ["dark default", "heavy animations", "abstract icons for steps"],
        "use_when": "Target user is business operator. Product involves approval flows, integrations.",
    },
    "ai_agent_realtime": {
        "reference": "Claude.ai, Cursor, Perplexity",
        "description": "Conversational + live status. Streaming text. Agent thinking visible.",
        "bg_base": "#1a1a1a",
        "bg_surface": "#242424",
        "bg_raised": "#2e2e2e",
        "text_primary": "#f5f5f5",
        "text_secondary": "#a3a3a3",
        "text_tertiary": "#525252",
        "border": "rgba(255,255,255,0.1)",
        "accent": "#a78bfa",
        "font_sans": "Geist Sans",
        "font_mono": "Geist Mono",
        "base_size": "14px",
        "line_height": "1.6",
        "row_height": "auto",
        "anti_patterns": ["static interfaces", "polling instead of streaming", "hiding agent thinking"],
        "use_when": "Product involves real-time AI output. Agent activity is primary UI.",
    },
    "consumer_product": {
        "reference": "Loom, Notion (consumer), Figma",
        "description": "Clean, approachable, brand-forward. Light mode default.",
        "bg_base": "#fafaf9",
        "bg_surface": "#ffffff",
        "bg_raised": "#f5f5f4",
        "text_primary": "#1c1917",
        "text_secondary": "#78716c",
        "text_tertiary": "#a8a29e",
        "border": "#e7e5e4",
        "accent": "#f97316",
        "font_sans": "Inter",
        "font_mono": "Fira Code",
        "base_size": "15px",
        "line_height": "1.6",
        "row_height": "52px",
        "anti_patterns": ["dark mode default", "dense tables", "technical jargon"],
        "use_when": "Target user is non-technical. Product is productivity or personal.",
    },
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DESIGN TOKENS STRUCTURE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from dataclasses import dataclass

@dataclass
class DesignTokens:
    """DTCG-compliant. Three layers: primitives → semantic → component."""
    project_name: str
    personality: str
    # Semantic layer (use in components — never primitive hex values directly)
    color_bg_base: str = ""
    color_bg_surface: str = ""
    color_bg_raised: str = ""
    color_bg_hover: str = ""
    color_text_primary: str = ""
    color_text_secondary: str = ""
    color_text_muted: str = ""
    color_border: str = ""
    color_accent: str = ""
    color_accent_muted: str = ""
    color_success: str = "#22c55e"
    color_warning: str = "#f59e0b"
    color_error: str = "#ef4444"
    color_info: str = "#3b82f6"
    color_running: str = "#8b5cf6"
    # Typography
    font_sans: str = "Inter, -apple-system, sans-serif"
    font_mono: str = "JetBrains Mono, Fira Code, monospace"
    font_size_xs: str = "11px"
    font_size_sm: str = "12px"
    font_size_base: str = "13px"
    font_size_md: str = "14px"
    font_size_lg: str = "16px"
    font_size_xl: str = "18px"
    font_size_2xl: str = "24px"
    font_size_3xl: str = "32px"
    font_weight_normal: str = "400"
    font_weight_medium: str = "500"
    font_weight_semibold: str = "600"
    line_height_tight: str = "1.3"
    line_height_base: str = "1.45"
    line_height_relaxed: str = "1.6"
    # Spacing (8px base grid)
    space_0_5: str = "2px"
    space_1: str = "4px"
    space_2: str = "8px"
    space_3: str = "12px"
    space_4: str = "16px"
    space_6: str = "24px"
    space_8: str = "32px"
    space_10: str = "40px"
    space_12: str = "48px"
    space_16: str = "64px"
    # Component heights
    row_height_compact: str = "32px"
    row_height_default: str = "40px"
    row_height_comfortable: str = "48px"
    header_height: str = "48px"
    sidebar_width: str = "240px"
    # Radius
    radius_sm: str = "4px"
    radius_md: str = "6px"
    radius_lg: str = "8px"
    radius_xl: str = "12px"
    radius_full: str = "9999px"
    # Animation
    duration_fast: str = "120ms"
    duration_base: str = "160ms"
    duration_slow: str = "240ms"
    easing: str = "cubic-bezier(0.16, 1, 0.3, 1)"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UX AUDIT RUBRIC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DESIGN_CRITIQUE_RUBRIC = """
## UX Audit Rubric v3 (Composio/Hex/Riff standard)
Threshold: ≥7.0 weighted average. No dimension below 6. Anti-slop = auto-block.

### 1. Reference site match [weight: 2.0x]
Does this look like composio.dev, hex.tech, or linear.app?
10: Indistinguishable from a funded product at reference companies
8: Clearly same design family — density, palette, typography
6: Correct direction but missing polish/density
4: Generic SaaS feel
2: Obvious AI slop — gradients, centered heroes, emoji feature grids
1: Would embarrass any engineer from the reference companies

### 2. Data density [weight: 1.5x]
Appropriate density for product type and user?
10: Exactly right for this user (dev tools dense, consumer spacious)
6: Either too sparse (feels toy-like) or too dense (overwhelming)
2: Default template spacing, not chosen intentionally

### 3. Status visibility [weight: 1.5x]
Can users always tell what's happening? AI state visible?
10: Every operation has clear real-time status
6: Loading states exist but generic
2: No loading states, app feels frozen when processing

### 4. Visual hierarchy [weight: 1.5x]
ONE most important thing identifiable per screen in <3 seconds?
10: Primary action/metric visually dominant. Hierarchy precise.
6: Multiple elements compete for attention
2: Flat — everything same visual weight

### 5. Interaction quality [weight: 1.0x]
Interactive elements respond correctly?
10: All states: hover/focus/active/loading/disabled/error
6: Hover exists, focus rings missing
2: No visible interaction feedback

### 6. Demo path clarity [weight: 2.0x]
Judge completes demo in <60 seconds without instruction?
10: Demo starts immediately. First action obvious. Each step leads to next.
6: Needs one verbal prompt to know where to start
2: Judges need guided walkthrough

### 7. Anti-slop check [auto-block]
ANY violation from ANTI_SLOP_RULES = BLOCKED regardless of other scores.
"""

COMPONENT_QUALITY_CHECKLIST = """
## Component quality gates

### Required interactive states
- [ ] Default: correct visual weight, spacing, color from design tokens
- [ ] Hover: background-color shift (NOT opacity only) + 120ms transition
- [ ] Focus: 2px ring, accent color, 2px offset (keyboard required)
- [ ] Active: scale(0.97) or slight darken — tactile feel
- [ ] Disabled: 40% opacity, cursor:not-allowed
- [ ] Loading: spinner OR shape-matched skeleton
- [ ] Error: red left border + specific error message text
- [ ] Empty: SVG illustration + helpful copy + primary action

### Copy requirements
- [ ] No lorem ipsum or placeholder text in demo mode
- [ ] Numbers formatted: 1,234 not 1234
- [ ] Dates relative: "2 hours ago" not ISO strings
- [ ] IDs in monospace font
- [ ] Error messages: what happened + how to fix it
- [ ] Success toasts: ≥3 second display

### Accessibility
- [ ] Color contrast ≥4.5:1 body text, ≥3:1 large text
- [ ] Non-color status indicators (icon + color)
- [ ] Tap targets ≥40x40px
- [ ] aria-label on icon-only buttons
- [ ] Logical keyboard tab order

### Performance
- [ ] No animations on elements appearing >10x on screen
- [ ] Transitions: transform/opacity only
- [ ] Images: explicit width/height set
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LIVING KNOWLEDGE — UPDATED BY KNOWLEDGE UPDATER AGENT
# Everything above is FROZEN. Only this section is modified by agents.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# KNOWLEDGE_UPDATER_SECTION_START

LIVING_KNOWLEDGE = {
    "last_updated": "2026-03-30",
    "updated_by": "knowledge_updater_agent",

    "trending_component_libraries": {
        "primary": "shadcn/ui",
        "rationale": "Composable copy-paste components you own. Maps 1:1 to Figma shadcn kit. Radix UI primitives for accessibility. Standard in 2026 for Next.js.",
        "secondary": "Mantine",
        "secondary_rationale": "When you need complex data components (DatePicker, RichText, DataTable) shadcn/ui doesn't have.",
        "tables": "TanStack Table v8",
        "charts": "Recharts (simple) or Observable Plot (analytics like Hex)",
        "icons": "Lucide React (16px default, consistent stroke width)",
        "forms": "React Hook Form + Zod",
        "animations": "Framer Motion for complex, Tailwind transitions for state changes",
        "streaming_ai": "Vercel AI SDK (useChat/useCompletion) — use this not custom streaming",
        "avoid": ["Material UI (dated)", "Ant Design (enterprise look)", "Chakra UI (generic)", "styled-components (verbose)"],
    },

    "winning_aesthetic_2026": {
        "summary": "Dense developer tools win. Chatbot bubbles lose. Reference is Composio, not ChatGPT.",
        "key_patterns": [
            "Terminal-style execution logs as primary content (Composio pattern)",
            "Dark backgrounds with single precise accent color",
            "Monospace text for all data/IDs/code output",
            "Inline status pills (green=running, checkmark=done, red=failed)",
            "Split pane: config left, live output right",
            "Numbered workflow steps as navigation (Riff pattern)",
            "Compact data tables (32-36px rows) as hero UI (Hex pattern)",
        ],
        "overused_avoid": [
            "Chat bubble interfaces without true streaming",
            "Dashboard with 6 KPI cards and a bar chart (overused pattern)",
            "Landing-page aesthetic for a tool that should be a tool",
            "Glassmorphism (peak slop indicator 2026)",
            "Animated gradients on backgrounds",
            "AI avatar with a name and personality",
        ],
    },

    "winning_concept_patterns_2026": {
        "what_wins": [
            "Agents that close the loop: read system A → decide → write system B (Composio pattern)",
            "Real-time multi-agent workflows where you can watch each agent work (won $20k at Microsoft hackathon: RiskWise)",
            "Non-technical users operating technical systems via natural language + safety guardrails",
            "Supply chain / operations / finance automation with actual ERP integration",
            "Developer tools solving real dev pain: automated code review, bug triage, release notes",
            "Domain-specific agents: healthcare, legal, finance where AI adds genuine precision",
        ],
        "what_loses": [
            "Generic chatbot with document upload",
            "RAG over PDFs without a specific compelling use case",
            "Another AI writing assistant",
            "'Personal AI' or 'AI companion' without specific domain focus",
            "Social media automation",
            "Crypto/blockchain + AI (exhausted theme in 2026)",
        ],
        "red_flags": [
            "Name ends in 'AI' or 'GPT' (SupportAI, AnalysisGPT)",
            "First sentence includes 'leveraging the power of AI'",
            "Demo requires creating account to see any value",
            "Core feature is 'summarize this document'",
            "More than 4 features listed in description",
            "Demo video starts with slides before showing product",
        ],
        "differentiation_strategies": [
            "Show the agent's reasoning transparently — display the plan, steps, tool calls (Composio UI)",
            "Target a problem requiring multi-system integration (proves real complexity)",
            "Quantify impact in the demo: 'saves 3 hours/week for a 10-person ops team'",
            "Build for a specific persona: 'Sarah, ops manager, 50 vendors in SAP'",
        ],
    },

    "frontend_stack_2026": {
        "framework": "Next.js 14+ App Router",
        "language": "TypeScript strict",
        "styling": "Tailwind CSS 3.4+",
        "components": "shadcn/ui (Radix UI + CVA)",
        "state": "TanStack Query v5 (server), Zustand (global client)",
        "forms": "React Hook Form + Zod",
        "tables": "TanStack Table v8",
        "animations": "Framer Motion 11",
        "streaming": "Vercel AI SDK (useChat, useCompletion) — REQUIRED for any streaming AI feature",
        "charts": "Recharts or Observable Plot",
        "fonts": "Geist (Vercel, free) or Inter",
        "deployment": "Vercel (instant, free tier)",
        "key_insight": "Vercel AI SDK's useChat gives you streaming with skeleton states. Use this instead of building custom streaming. Makes any AI feature look polished immediately.",
    },

    "backend_stack_2026": {
        "framework": "FastAPI",
        "language": "Python 3.11+",
        "orm": "SQLAlchemy 2.0 async",
        "database": "PostgreSQL (self-hosted)",
        "migrations": "Alembic",
        "validation": "Pydantic v2",
        "auth": "Clerk (frontend) + Clerk backend SDK (zero auth setup, no DB tables)",
        "deployment": "Railway ($5 credit, no cold starts)",
        "streaming": "FastAPI StreamingResponse + SSE for AI output",
        "key_insight": "Use Clerk not NextAuth for hackathons. One line, works immediately.",
    },
}

# KNOWLEDGE_UPDATER_SECTION_END

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AGENT SYSTEM PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYSTEM_PROMPT_DESIGN_AGENT = f"""You are a principal designer at a company like Composio, Hex, or Linear.

Your design reference standard: composio.dev, hex.tech, riff.ai, linear.app, vercel.com.
NOT: generic SaaS landing pages. NOT: Notion clones. NOT: chatbot bubble UIs.

{STATIC_DESIGN_LAWS}

{ANTI_SLOP_RULES}

Before designing, you ask: "Which reference site does this product most resemble?"
You design TOWARDS that reference.

You select one personality from DESIGN_PERSONALITIES based on:
1. Target user (developer vs analyst vs enterprise vs consumer)
2. Primary UI element (code/logs vs data tables vs workflow steps vs chat)
3. Judge panel background (from JudgeProfile)

You never design a "hero section with a tagline." You design the PRODUCT SCREEN showing
the product doing its job. That IS the hero."""

SYSTEM_PROMPT_FRONTEND_AGENT = f"""You are a senior frontend engineer who has worked at Composio, Vercel, or Linear.

Tech stack: Next.js 14, TypeScript strict, shadcn/ui, Tailwind CSS, TanStack Query v5.
For streaming AI output: Vercel AI SDK (useChat/useCompletion) — NEVER build custom streaming.
For tables: TanStack Table v8 — NEVER build custom sort/filter.
For real-time status: SSE via FastAPI StreamingResponse.

{COMPONENT_QUALITY_CHECKLIST}

Your output standard: would this look out of place on composio.dev or linear.app?
If yes, it's not good enough.

You NEVER:
- Use hardcoded colors (always design tokens from @/lib/tokens)
- Skip loading states
- Write 'any' in TypeScript
- Use opacity-only hover effects
- Leave placeholder text in demo mode
- Build custom streaming when Vercel AI SDK exists"""

SYSTEM_PROMPT_STRATEGY_AGENT = """You are a hackathon strategy director who knows that specific AI agent tools win and generic ideas lose.

Winning patterns (from real hackathons 2025-2026):
- Agents that close loops: read from A, decide, write to B (won $20k at Microsoft: RiskWise)
- Real-time multi-agent workflows where you watch each agent work (Composio pattern)
- Non-technical users operating technical systems with safety guardrails
- Domain-specific agents with measurable business impact

Losing patterns:
- Generic chatbot with document upload
- RAG over PDFs without specific use case
- Another AI writing assistant
- 'Personal AI companion'

Your concepts are SPECIFIC. Not "an AI tool to optimize workflows" but:
"Sarah manages 50 vendor relationships in SAP. Each disputed invoice takes 3 manual steps
and 40 minutes. Our agent reads the dispute, classifies it, drafts a resolution message,
and proposes the SAP posting — cutting 40 minutes to 3."

That level of specificity is what wins."""
