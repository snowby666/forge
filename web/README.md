# Forge Web Dashboard

Browser-based management UI for the Forge autonomous hackathon swarm.

## Stack

- **Next.js 15** (App Router) — React server components + client components
- **shadcn/ui** — Component library (Radix primitives + Tailwind)
- **Tailwind CSS** — Utility-first styling with JetBrains Mono typography
- **framer-motion** — Animations and transitions
- **SWR** — Data fetching with real-time revalidation
- **sonner** — Toast notifications
- **cmdk** — Command palette (Ctrl+K)

## Pages

| Route | Description |
|---|---|
| `/` | Dashboard — summary cards, pending checkpoints, recent activity |
| `/hackathons` | List all hackathons with phase, status, actions |
| `/hackathon/[id]` | Detail — agent timeline, checkpoints, design, performance, artifacts |
| `/hackathon` | Live Logs hub — recent runs, log viewer |
| `/analytics` | Cost charts, agent timing, success rates |
| `/settings` | API keys, service health, config editor |

## Setup

```bash
npm install
```

### Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Environment

The frontend proxies all `/api/*` requests to the Forge API backend (`forge_web/`).

| Variable | Default | Description |
|---|---|---|
| `FORGE_WEB_TOKEN` | (auto-generated) | Login password for the dashboard |
| `NEXT_PUBLIC_API_URL` | `http://localhost:3001` | API backend URL (used by `next.config.ts` rewrites) |

### Production

```bash
npm run build
npm start
```

Or via Docker:

```bash
docker compose up -d web
```

## Architecture

```
web/src/
  app/
    (dashboard)/          # Authenticated layout with sidebar
      hackathon/[id]/     # Hackathon detail page
      hackathons/         # Hackathon list page
      analytics/          # Analytics page
      settings/           # Settings page
    login/                # Login page (no sidebar)
    layout.tsx            # Root layout
  components/             # Shared components (sidebar, tables, timeline, etc.)
  hooks/                  # Custom hooks (useAgentStatus, useRealtimeStatus)
  lib/
    api.ts                # API client functions
    types.ts              # TypeScript interfaces
    utils.ts              # Utility functions
```

## Relationship to `forge_web/`

This Next.js app is a pure frontend. It communicates exclusively via:

1. **REST API** — `GET/POST/PUT/DELETE /api/*` endpoints served by `forge_web/`
2. **WebSocket** — `/api/ws` for real-time agent status updates

The `next.config.ts` rewrites proxy these requests to the backend at `NEXT_PUBLIC_API_URL`.
