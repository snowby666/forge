"use client"

import { useCallback } from "react"
import Link from "next/link"
import useSWR from "swr"
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  DollarSign,
  ExternalLink,
  Trophy,
  Zap,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { useHackathons } from "@/hooks/use-hackathons"
import {
  approveCheckpoint,
  fetchCheckpoints,
  fetchServiceHealth,
} from "@/lib/api"
import type { AgentPhaseName, Checkpoint, ServiceHealth } from "@/lib/types"

const PHASES: AgentPhaseName[] = [
  "intelligence",
  "strategy",
  "design",
  "build",
  "verify",
  "polish",
  "submission",
  "infra",
]

const PHASE_ABBR: Record<AgentPhaseName, string> = {
  intelligence: "INT",
  strategy: "STR",
  design: "DES",
  build: "BLD",
  verify: "VER",
  polish: "POL",
  submission: "SUB",
  infra: "INF",
}

const PHASE_BADGE: Record<string, string> = {
  intelligence: "border-blue-500/20 bg-blue-500/10 text-blue-400",
  strategy: "border-violet-500/20 bg-violet-500/10 text-violet-400",
  design: "border-pink-500/20 bg-pink-500/10 text-pink-400",
  build: "border-amber-500/20 bg-amber-500/10 text-amber-400",
  verify: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
  polish: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",
  submission: "border-orange-500/20 bg-orange-500/10 text-orange-400",
  infra: "border-zinc-500/20 bg-zinc-500/10 text-zinc-400",
}

function deadlineLabel(days: number) {
  if (days < 0) return "Expired"
  if (days === 0) return "Today"
  if (days === 1) return "Tomorrow"
  return `${days}d left`
}

function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-400"
  if (score >= 60) return "text-yellow-400"
  if (score >= 40) return "text-orange-400"
  return "text-red-400"
}

function phaseStatus(
  hackathonPhase: AgentPhaseName,
  cellPhase: AgentPhaseName,
): "done" | "active" | "pending" {
  const hIdx = PHASES.indexOf(hackathonPhase)
  const cIdx = PHASES.indexOf(cellPhase)
  if (cIdx < hIdx) return "done"
  if (cIdx === hIdx) return "active"
  return "pending"
}

export default function DashboardPage() {
  const { hackathons, isLoading: hackLoading } = useHackathons()

  const { data: checkpoints, mutate: mutateCheckpoints } = useSWR<
    Checkpoint[]
  >("/api/checkpoints", fetchCheckpoints, { refreshInterval: 10_000 })

  const { data: health } = useSWR<ServiceHealth[]>(
    "/api/services/health",
    fetchServiceHealth,
    { refreshInterval: 30_000 },
  )

  const pendingCheckpoints = checkpoints?.filter((c) => c.pending) ?? []
  const activePipelines = hackathons.filter(
    (h) => h.phase !== "submission",
  ).length
  const totalPrizeTracks = hackathons.reduce(
    (sum, h) => sum + (h.brief.prizes?.length ?? 0),
    0,
  )
  const recentHackathons = hackathons.slice(0, 5)

  const handleApproveAll = useCallback(async () => {
    if (pendingCheckpoints.length === 0) return
    await Promise.all(
      pendingCheckpoints.map((cp) =>
        approveCheckpoint(cp.hackathon_id, cp.checkpoint),
      ),
    )
    mutateCheckpoints()
  }, [pendingCheckpoints, mutateCheckpoints])

  const summaryCards = [
    {
      title: "Total Hackathons",
      value: hackathons.length,
      icon: Trophy,
      color: "text-blue-400",
      bg: "bg-blue-500/10",
    },
    {
      title: "Pending Approvals",
      value: pendingCheckpoints.length,
      icon: Clock,
      color: "text-yellow-400",
      bg: "bg-yellow-500/10",
    },
    {
      title: "Active Pipelines",
      value: activePipelines,
      icon: Activity,
      color: "text-emerald-400",
      bg: "bg-emerald-500/10",
    },
    {
      title: "Prize Tracks",
      value: totalPrizeTracks,
      icon: DollarSign,
      color: "text-violet-400",
      bg: "bg-violet-500/10",
    },
  ]

  if (hackLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <div className="h-4 w-24 animate-pulse rounded bg-muted" />
              </CardHeader>
              <CardContent>
                <div className="h-8 w-16 animate-pulse rounded bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-28 animate-pulse rounded-lg bg-muted/50"
            />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summaryCards.map((card) => (
          <Card key={card.title}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardDescription className="text-xs font-medium">
                {card.title}
              </CardDescription>
              <div className={`rounded-md p-1.5 ${card.bg}`}>
                <card.icon className={`size-4 ${card.color}`} />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold tabular-nums">{card.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {recentHackathons.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Agent Activity
          </h2>
          <Card>
            <CardContent className="overflow-x-auto pt-4">
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className="pb-2 pr-4 text-left font-medium text-muted-foreground">
                      Hackathon
                    </th>
                    {PHASES.map((p) => (
                      <th
                        key={p}
                        className="pb-2 text-center font-mono font-medium text-muted-foreground"
                      >
                        {PHASE_ABBR[p]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {recentHackathons.map((h) => (
                    <tr key={h.id} className="border-t border-border/50">
                      <td className="max-w-[160px] truncate py-2 pr-4 font-medium">
                        <Link
                          href={`/hackathon/${h.id}`}
                          className="hover:underline"
                        >
                          {h.brief.name}
                        </Link>
                      </td>
                      {PHASES.map((p) => {
                        const s = phaseStatus(h.phase, p)
                        return (
                          <td key={p} className="py-2 text-center">
                            <span
                              className={`mx-auto block size-2.5 rounded-full ${
                                s === "done"
                                  ? "bg-emerald-500"
                                  : s === "active"
                                    ? "animate-pulse bg-yellow-500"
                                    : "bg-zinc-700"
                              }`}
                            />
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Quick Actions
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            render={<Link href="/settings" />}
          >
            <Zap className="mr-1.5 size-3.5" />
            Run Scout
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pendingCheckpoints.length === 0}
            onClick={handleApproveAll}
          >
            <CheckCircle2 className="mr-1.5 size-3.5" />
            Approve All ({pendingCheckpoints.length})
          </Button>
          {hackathons[0] && (
            <Button
              variant="outline"
              size="sm"
              render={<Link href={`/hackathon/${hackathons[0].id}`} />}
            >
              <ExternalLink className="mr-1.5 size-3.5" />
              View Logs
            </Button>
          )}
        </div>
      </section>

      <Separator />

      {pendingCheckpoints.length > 0 && (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Pending Approvals
            </h2>
            <Badge
              variant="outline"
              className="border-yellow-500/30 text-yellow-500"
            >
              {pendingCheckpoints.length}
            </Badge>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {pendingCheckpoints.map((cp) => {
              const hack = hackathons.find((h) => h.id === cp.hackathon_id)
              return (
                <Link
                  key={`${cp.hackathon_id}-${cp.checkpoint}`}
                  href={`/hackathon/${cp.hackathon_id}/approve/${cp.checkpoint}`}
                >
                  <Card className="group transition-colors hover:border-yellow-500/50 hover:bg-accent/30">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm">
                        {hack?.brief.name ?? cp.hackathon_id}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="flex items-center justify-between">
                      <Badge
                        variant="outline"
                        className="border-yellow-500/30 text-[10px] capitalize text-yellow-500"
                      >
                        {cp.checkpoint.replace(/_/g, " ")}
                      </Badge>
                      <span className="flex items-center gap-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                        Review
                        <ArrowRight className="size-3" />
                      </span>
                    </CardContent>
                  </Card>
                </Link>
              )
            })}
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Active Hackathons
        </h2>
        {hackathons.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No hackathons yet.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hackathons.map((h) => (
              <Link key={h.id} href={`/hackathon/${h.id}`}>
                <Card className="transition-colors hover:bg-accent/30">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="truncate text-sm">
                        {h.brief.name}
                      </CardTitle>
                      <span
                        className={`font-mono text-sm font-bold ${scoreColor(h.brief.score)}`}
                      >
                        {h.brief.score}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className={`text-[10px] capitalize ${PHASE_BADGE[h.phase] ?? ""}`}
                    >
                      {h.phase}
                    </Badge>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {deadlineLabel(h.brief.days_until_deadline)}
                    </span>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </section>

      {health && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            System Health
          </h2>
          <Card>
            <CardContent className="flex flex-wrap gap-6 pt-6">
              {health.map((s) => (
                <div key={s.name} className="flex items-center gap-2">
                  <span
                    className={`inline-block size-2.5 rounded-full ${
                      s.status === "ok" ? "bg-emerald-500" : "bg-red-500"
                    }`}
                  />
                  <span className="text-sm capitalize">{s.name}</span>
                  {s.latency_ms != null && (
                    <span className="font-mono text-xs text-muted-foreground">
                      {s.latency_ms}ms
                    </span>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  )
}
