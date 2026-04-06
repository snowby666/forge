"use client"

import Link from "next/link"
import useSWR from "swr"
import {
  Activity,
  CheckCircle2,
  Clock,
  DollarSign,
  Trophy,
  XCircle,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useHackathons } from "@/hooks/use-hackathons"
import { fetchCheckpoints, fetchServiceHealth } from "@/lib/api"
import type { Checkpoint, ServiceHealth } from "@/lib/types"

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

function ServiceDot({ service }: { service: ServiceHealth }) {
  const ok = service.status === "ok"
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-block size-2.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
      />
      <span className="text-sm capitalize">{service.name}</span>
      {service.latency_ms != null && (
        <span className="text-xs text-muted-foreground">
          {service.latency_ms}ms
        </span>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const { hackathons, isLoading: hackLoading } = useHackathons()

  const { data: checkpoints } = useSWR<Checkpoint[]>(
    "/api/checkpoints",
    fetchCheckpoints,
    { refreshInterval: 10_000 },
  )

  const { data: health } = useSWR<ServiceHealth[]>(
    "/api/services/health",
    fetchServiceHealth,
    { refreshInterval: 30_000 },
  )

  const pendingCheckpoints = checkpoints?.filter((c) => c.pending) ?? []
  const runningAgents = hackathons.filter(
    (h) => h.phase !== "submission",
  ).length
  const totalPrize = hackathons.reduce(
    (sum, h) => sum + (h.brief.prizes?.length ?? 0),
    0,
  )

  const summaryCards = [
    {
      title: "Total Hackathons",
      value: hackathons.length,
      icon: Trophy,
      color: "text-blue-400",
    },
    {
      title: "Pending Approvals",
      value: pendingCheckpoints.length,
      icon: Clock,
      color: "text-yellow-400",
    },
    {
      title: "Active Pipelines",
      value: runningAgents,
      icon: Activity,
      color: "text-emerald-400",
    },
    {
      title: "Prize Tracks",
      value: totalPrize,
      icon: DollarSign,
      color: "text-violet-400",
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
              <card.icon className={`size-4 ${card.color}`} />
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{card.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {pendingCheckpoints.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Pending Approvals
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {pendingCheckpoints.map((cp) => (
              <Link
                key={`${cp.hackathon_id}-${cp.checkpoint}`}
                href={`/hackathon/${cp.hackathon_id}/approve/${cp.checkpoint}`}
              >
                <Card className="transition-colors hover:border-yellow-500/50 hover:bg-accent/30">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">
                      {cp.checkpoint.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </CardTitle>
                    <CardDescription className="truncate text-xs">
                      {cp.hackathon_id}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Badge
                      variant="outline"
                      className="animate-pulse border-yellow-500/50 text-yellow-500"
                    >
                      <Clock className="mr-1 size-3" />
                      Awaiting Review
                    </Badge>
                  </CardContent>
                </Card>
              </Link>
            ))}
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
                <ServiceDot key={s.name} service={s} />
              ))}
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  )
}
