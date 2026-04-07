"use client"

import { use, useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import { formatDistanceToNow } from "date-fns"
import { motion } from "framer-motion"
import { toast } from "sonner"
import TraceViewer from "@/components/trace-viewer"
import ArtifactRegistryView from "@/components/artifact-registry"
import {
  ArrowLeft,
  Clock,
  DollarSign,
  ExternalLink,
  Palette,
  Play,
  RefreshCw,
  ScrollText,
  Trash2,
  Users,
  Zap,
} from "lucide-react"
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { AgentTimeline } from "@/components/agent-timeline"
import { CheckpointCard } from "@/components/checkpoint-card"
import type { ConceptOption } from "@/components/checkpoint-card"
import { useAgentStatus } from "@/hooks/use-agent-status"
import {
  approveCheckpoint,
  deleteHackathon,
  fetchAnalytics,
  fetchCheckpoints,
  fetchHackathons,
  rerollHackathon,
  fetchCost,
  fetchElapsed,
  restartAgent,
  runHackathon,
  triggerAgent,
} from "@/lib/api"
import { ALL_AGENT_IDS } from "@/lib/types"
import type { AgentPhaseName, AnalyticsData, Checkpoint, Hackathon } from "@/lib/types"

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

const PHASE_BAR_COLORS: Record<string, string> = {
  intelligence: "#60a5fa",
  strategy: "#a78bfa",
  design: "#f472b6",
  build: "#fbbf24",
  verify: "#34d399",
  polish: "#22d3ee",
  submission: "#fb923c",
  infra: "#a1a1aa",
}

function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-400"
  if (score >= 60) return "text-yellow-400"
  if (score >= 40) return "text-orange-400"
  return "text-red-400"
}

function deadlineLabel(days: number) {
  if (days < 0) return "Expired"
  if (days === 0) return "Today"
  if (days === 1) return "Tomorrow"
  return `${days}d left`
}

function MiniProgressRing({ value, size = 36 }: { value: number; size?: number }) {
  const strokeWidth = 3
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (value / 100) * circumference

  return (
    <svg width={size} height={size} className="shrink-0 -rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        className="text-muted/50"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        className="text-blue-500 transition-all duration-500"
      />
    </svg>
  )
}

export default function HackathonDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [rerollOpen, setRerollOpen] = useState(false)
  const [runMenuOpen, setRunMenuOpen] = useState(false)

  const { data: hackathons } = useSWR<Hackathon[]>(
    "/api/hackathons",
    fetchHackathons,
    { refreshInterval: 15_000 },
  )
  const hackathon = hackathons?.find((h) => h.id === id)

  const { agents, connected } = useAgentStatus(id)

  const { data: checkpoints, mutate: mutateCheckpoints } = useSWR<Checkpoint[]>(
    "/api/checkpoints",
    fetchCheckpoints,
    { refreshInterval: 10_000 },
  )
  const hackCheckpoints = checkpoints?.filter((c) => c.hackathon_id === id) ?? []


  const { data: analytics } = useSWR<AnalyticsData>(
    `/api/analytics/${id}`,
    () => fetchAnalytics(id),
    { refreshInterval: 60_000 },
  )

  const { data: costData } = useSWR(
    `/api/hackathon/${id}/cost`,
    () => fetchCost(id),
    { refreshInterval: 15_000 },
  )

  const { data: elapsedData } = useSWR(
    `/api/hackathon/${id}/elapsed`,
    () => fetchElapsed(id),
    { refreshInterval: 10_000 },
  )

  const { doneCount, totalAgents, pct } = useMemo(() => {
    const total = ALL_AGENT_IDS.length
    const done = agents.filter((a) => a.status === "done").length
    return { doneCount: done, totalAgents: total, pct: total > 0 ? Math.round((done / total) * 100) : 0 }
  }, [agents])

  const sortedCheckpoints = useMemo(() => {
    const pending = hackCheckpoints.filter((c) => c.pending)
    const approved = hackCheckpoints.filter((c) => !c.pending)
    return [...pending, ...approved]
  }, [hackCheckpoints])

  const handleTrigger = useCallback(
    async (agentId: string) => {
      try {
        await triggerAgent(id, agentId)
        toast.success(`Triggered ${agentId.replace(/_/g, " ")}`)
      } catch {
        toast.error(`Failed to trigger ${agentId}`)
      }
    },
    [id],
  )

  const handleRestart = useCallback(
    async (agentId: string) => {
      try {
        await restartAgent(id, agentId)
        toast.success(`Restarted ${agentId.replace(/_/g, " ")}`)
      } catch {
        toast.error(`Failed to restart ${agentId}`)
      }
    },
    [id],
  )

  const handleRerollConfirm = useCallback(async () => {
    try {
      await rerollHackathon(id)
      setRerollOpen(false)
      toast.success("Pipeline rerolled")
    } catch {
      toast.error("Failed to reroll")
    }
  }, [id])

  const handleDeleteConfirm = useCallback(async () => {
    try {
      await deleteHackathon(id)
      toast.success("Hackathon deleted")
      router.push("/hackathons")
    } catch {
      toast.error("Failed to delete hackathon")
    }
  }, [id, router])

  const handleApprove = useCallback(
    async (cp: Checkpoint, data?: Record<string, unknown>) => {
      try {
        await approveCheckpoint(id, cp.checkpoint, data)
        mutateCheckpoints()
        toast.success(`${cp.checkpoint.replace(/_/g, " ")} approved`)
      } catch {
        toast.error("Failed to approve checkpoint")
      }
    },
    [id, mutateCheckpoints],
  )

  const handleRunPipeline = useCallback(
    async (opts?: { from_phase?: string; restart?: boolean }) => {
      try {
        await runHackathon(id, opts)
        toast.success(
          opts?.restart
            ? "Pipeline restarting..."
            : opts?.from_phase
              ? `Pipeline resuming from ${opts.from_phase}...`
              : "Pipeline resumed!",
        )
      } catch {
        toast.error("Failed to run pipeline")
      }
    },
    [id],
  )

  if (!hackathon) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-muted" />
        <div className="h-2 w-full animate-pulse rounded-full bg-muted" />
        <div className="grid gap-4 sm:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-muted/50" />
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-lg bg-muted/50" />
      </div>
    )
  }

  const { brief } = hackathon
  const totalElapsedS = elapsedData?.total_elapsed_s
  const startedAt = elapsedData?.started_at ?? (brief.started_at as string | undefined)
  const costUsd = costData?.total_usd ?? analytics?.cost_by_hackathon?.find(
    (c) => c.name === brief.name,
  )?.cost_usd ?? (analytics as Record<string, unknown> | undefined)?.cost_usd as number | undefined

  return (
    <div className="space-y-6">
      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Pipeline Progress</span>
          <span className="font-mono font-medium text-foreground">{pct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500"
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          />
        </div>
      </div>

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Link href="/hackathons">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight">{brief.name}</h1>
              <Badge variant="outline" className={`font-mono text-xs font-bold ${scoreColor(brief.score)}`}>
                {brief.score}/100
              </Badge>
              <Badge
                variant="outline"
                className={`text-[10px] capitalize ${PHASE_BADGE[hackathon.phase] ?? ""}`}
              >
                {hackathon.phase}
              </Badge>
              <span
                className={`inline-block size-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`}
                title={connected ? "WebSocket connected" : "WebSocket disconnected"}
              />
            </div>
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="size-3" />
              {deadlineLabel(brief.days_until_deadline)}
              {brief.url && (
                <>
                  <span className="text-muted-foreground/40">·</span>
                  <a
                    href={brief.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 hover:text-foreground hover:underline"
                  >
                    Hackathon Page
                    <ExternalLink className="size-3" />
                  </a>
                </>
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Button size="sm" onClick={() => setRunMenuOpen((v) => !v)}>
              <Play className="mr-1.5 size-3.5" />
              Run Pipeline
            </Button>
            {runMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setRunMenuOpen(false)} />
                <div className="absolute right-0 top-full z-50 mt-1 w-48 rounded-lg border bg-popover p-1 text-popover-foreground shadow-md">
                  <p className="px-2 py-1 text-xs font-medium text-muted-foreground">Run Options</p>
                  <div className="my-1 h-px bg-border" />
                  <button className="flex w-full items-center rounded-md px-2 py-1.5 text-sm hover:bg-accent" onClick={() => { setRunMenuOpen(false); handleRunPipeline() }}>
                    Resume
                  </button>
                  <button className="flex w-full items-center rounded-md px-2 py-1.5 text-sm hover:bg-accent" onClick={() => { setRunMenuOpen(false); handleRunPipeline({ restart: true }) }}>
                    Restart from scratch
                  </button>
                  <div className="my-1 h-px bg-border" />
                  <p className="px-2 py-1 text-xs font-medium text-muted-foreground">From Phase</p>
                  {(
                    [
                      "intelligence",
                      "strategy",
                      "design",
                      "build",
                      "verify",
                      "polish",
                      "submission",
                    ] as AgentPhaseName[]
                  ).map((phase) => (
                    <button
                      key={phase}
                      className="flex w-full items-center rounded-md px-2 py-1.5 text-sm capitalize hover:bg-accent"
                      onClick={() => { setRunMenuOpen(false); handleRunPipeline({ from_phase: phase }) }}
                    >
                      {phase}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <Link href={`/hackathon/${id}/logs`}>
            <Button variant="outline" size="sm">
              <ScrollText className="mr-1.5 size-3.5" />
              Logs
            </Button>
          </Link>
          <Link href={`/hackathon/${id}/design`}>
            <Button variant="outline" size="sm">
              <Palette className="mr-1.5 size-3.5" />
              Design
            </Button>
          </Link>
          <Separator orientation="vertical" className="!h-6" />
          <Button variant="outline" size="sm" onClick={() => setRerollOpen(true)}>
            <RefreshCw className="mr-1.5 size-3.5" />
            Reroll
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="mr-1.5 size-3.5" />
            Delete
          </Button>
        </div>
      </div>

      {/* Stats row — 4 cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <MiniProgressRing value={pct} />
            <div>
              <p className="text-xs text-muted-foreground">Agents Complete</p>
              <p className="font-mono text-lg font-bold tracking-tight">
                {doneCount}<span className="text-sm text-muted-foreground">/{totalAgents}</span>
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 items-center justify-center rounded-lg bg-violet-500/10">
              <Zap className="size-4 text-violet-400" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Current Phase</p>
              <Badge
                variant="outline"
                className={`mt-0.5 text-[10px] capitalize ${PHASE_BADGE[hackathon.phase] ?? ""}`}
              >
                {hackathon.phase}
              </Badge>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-500/10">
              <Clock className="size-4 text-emerald-400" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Time Elapsed</p>
              <p className="font-mono text-lg font-bold tracking-tight">
                {totalElapsedS != null
                  ? totalElapsedS >= 3600
                    ? `${Math.floor(totalElapsedS / 3600)}h ${Math.floor((totalElapsedS % 3600) / 60)}m`
                    : totalElapsedS >= 60
                      ? `${Math.floor(totalElapsedS / 60)}m ${Math.round(totalElapsedS % 60)}s`
                      : `${Math.round(totalElapsedS)}s`
                  : startedAt
                    ? formatDistanceToNow(new Date(startedAt), { addSuffix: false })
                    : "—"}
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 items-center justify-center rounded-lg bg-amber-500/10">
              <DollarSign className="size-4 text-amber-400" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Estimated Cost</p>
              <p className="font-mono text-lg font-bold tracking-tight">
                {costUsd !== undefined && costUsd !== null
                  ? `$${costUsd.toFixed(2)}`
                  : "—"}
              </p>
              {costData && costData.total_tokens > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  {(costData.total_tokens / 1000).toFixed(1)}k tokens
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="pipeline">
        <TabsList>
          <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
          <TabsTrigger value="checkpoints">
            Checkpoints
            {hackCheckpoints.filter((c) => c.pending).length > 0 && (
              <Badge variant="secondary" className="ml-1.5 size-5 justify-center rounded-full p-0 text-[10px]">
                {hackCheckpoints.filter((c) => c.pending).length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="traces">Traces</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
        </TabsList>

        {/* Pipeline tab */}
        <TabsContent value="pipeline" className="mt-4">
          {agents.length > 0 ? (
            <AgentTimeline
              agents={agents}
              hackathonId={id}
              onTrigger={handleTrigger}
              onRestart={handleRestart}
            />
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No agent data available yet.
            </p>
          )}
        </TabsContent>

        {/* Checkpoints tab */}
        <TabsContent value="checkpoints" className="mt-4">
          {sortedCheckpoints.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {sortedCheckpoints.map((cp) => {
                const concepts: ConceptOption[] | undefined =
                  cp.checkpoint === "concept_approval"
                    ? (cp.data.concepts as ConceptOption[] | undefined)
                    : undefined

                return (
                  <CheckpointCard
                    key={cp.checkpoint}
                    checkpoint={cp}
                    hackathonId={id}
                    concepts={concepts}
                    onApprove={(data) => handleApprove(cp, data)}
                  />
                )
              })}
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No checkpoints recorded yet.
            </p>
          )}
        </TabsContent>

        {/* Traces tab */}
        <TabsContent value="traces" className="mt-4">
          <TraceViewer hackathonId={id} />
        </TabsContent>

        {/* Artifacts tab */}
        <TabsContent value="artifacts" className="mt-4">
          <ArtifactRegistryView hackathonId={id} />
        </TabsContent>

        {/* Performance tab */}
        <TabsContent value="performance" className="mt-4 space-y-6">
          {analytics ? (
            <>
              {analytics.agent_timing && analytics.agent_timing.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Agent Timing (avg seconds)</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-[300px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={analytics.agent_timing}
                          layout="vertical"
                          margin={{ left: 120, right: 20, top: 5, bottom: 5 }}
                        >
                          <XAxis type="number" tick={{ fill: "#a1a1aa", fontSize: 11 }} />
                          <YAxis
                            type="category"
                            dataKey="agent_id"
                            tick={{ fill: "#a1a1aa", fontSize: 11 }}
                            tickFormatter={(v: string) =>
                              v.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())
                            }
                            width={115}
                          />
                          <RechartsTooltip
                            contentStyle={{
                              background: "#18181b",
                              border: "1px solid #27272a",
                              borderRadius: 8,
                              fontSize: 12,
                            }}
                            formatter={(value) => [`${Number(value).toFixed(1)}s`, "Avg Time"]}
                          />
                          <Bar dataKey="avg_seconds" radius={[0, 4, 4, 0]}>
                            {analytics.agent_timing.map((entry) => {
                              const agent = agents.find((a) => a.agent_id === entry.agent_id)
                              const color = agent
                                ? PHASE_BAR_COLORS[agent.phase] ?? "#60a5fa"
                                : "#60a5fa"
                              return (
                                <Cell key={entry.agent_id} fill={color} fillOpacity={0.7} />
                              )
                            })}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
              )}

              {analytics.success_rates && analytics.success_rates.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Agent Success Rates</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {analytics.success_rates.map((sr) => (
                        <div key={sr.agent_id} className="flex items-center gap-3">
                          <span className="w-32 shrink-0 truncate text-xs text-muted-foreground">
                            {sr.agent_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                          </span>
                          <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-muted">
                            <motion.div
                              className="absolute inset-y-0 left-0 rounded-full"
                              style={{
                                background:
                                  sr.success_pct >= 80
                                    ? "#34d399"
                                    : sr.success_pct >= 50
                                      ? "#fbbf24"
                                      : "#f87171",
                              }}
                              initial={{ width: 0 }}
                              animate={{ width: `${sr.success_pct}%` }}
                              transition={{ duration: 0.5, delay: 0.1 }}
                            />
                          </div>
                          <span className="w-14 shrink-0 text-right font-mono text-xs text-muted-foreground">
                            {sr.success_pct}%
                          </span>
                          <span className="w-16 shrink-0 text-right text-[10px] text-muted-foreground">
                            {sr.total_runs} runs
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {costData && costData.total_usd > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Cost Breakdown by Agent</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className="flex size-10 items-center justify-center rounded-lg bg-amber-500/10">
                        <DollarSign className="size-5 text-amber-400" />
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Total Estimated Cost</p>
                        <p className="font-mono text-2xl font-bold tracking-tight">
                          ${costData.total_usd.toFixed(2)}
                        </p>
                        <p className="text-[10px] text-muted-foreground">
                          {(costData.total_tokens / 1000).toFixed(1)}k tokens across{" "}
                          {Object.keys(costData.by_agent).length} agents
                        </p>
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      {Object.entries(costData.by_agent)
                        .sort(([, a], [, b]) => b.cost_usd - a.cost_usd)
                        .map(([aid, info]) => (
                          <div key={aid} className="flex items-center gap-2 text-xs">
                            <span className="w-36 truncate font-medium capitalize">
                              {aid.replace(/_/g, " ")}
                            </span>
                            <div className="flex-1">
                              <div
                                className="h-1.5 rounded-full bg-amber-500/50"
                                style={{ width: `${Math.max(4, (info.cost_usd / costData.total_usd) * 100)}%` }}
                              />
                            </div>
                            <span className="w-16 text-right font-mono text-muted-foreground">
                              ${info.cost_usd.toFixed(3)}
                            </span>
                            <span className="w-16 text-right font-mono text-[10px] text-muted-foreground">
                              {(info.tokens / 1000).toFixed(1)}k
                            </span>
                            <span className="w-12 text-right font-mono text-[10px] text-muted-foreground">
                              {info.calls} calls
                            </span>
                          </div>
                        ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {elapsedData && elapsedData.agent_times.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Agent Execution Times</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1.5">
                    {elapsedData.agent_times.map((at) => (
                      <div key={at.agent_id} className="flex items-center gap-2 text-xs">
                        <span className="w-36 truncate font-medium capitalize">
                          {at.agent_id.replace(/_/g, " ")}
                        </span>
                        <div className="flex-1">
                          <div
                            className="h-1.5 rounded-full bg-blue-500/50"
                            style={{
                              width: `${Math.max(4, (at.elapsed_s / Math.max(...elapsedData.agent_times.map((t) => t.elapsed_s))) * 100)}%`,
                            }}
                          />
                        </div>
                        <span className="w-16 text-right font-mono text-muted-foreground">
                          {at.elapsed_s >= 60
                            ? `${Math.floor(at.elapsed_s / 60)}m ${Math.round(at.elapsed_s % 60)}s`
                            : `${at.elapsed_s.toFixed(1)}s`}
                        </span>
                        <Badge
                          variant="outline"
                          className={`scale-75 ${at.status === "done" ? "border-emerald-500/40 text-emerald-400" : at.status === "failed" ? "border-red-500/40 text-red-400" : "border-blue-500/40 text-blue-400"}`}
                        >
                          {at.status}
                        </Badge>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {!analytics.agent_timing?.length &&
                !analytics.success_rates?.length &&
                (!costData || costData.total_usd === 0) &&
                (!elapsedData || !elapsedData.agent_times.length) && (
                  <p className="py-12 text-center text-sm text-muted-foreground">
                    No performance data available yet.
                  </p>
                )}
            </>
          ) : (
            <div className="space-y-4">
              <div className="h-[300px] animate-pulse rounded-lg bg-muted/50" />
              <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Reroll confirm dialog */}
      <Dialog open={rerollOpen} onOpenChange={setRerollOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reroll &ldquo;{brief.name}&rdquo;?</DialogTitle>
            <DialogDescription>
              This will restart the pipeline from scratch with a fresh strategy.
              Existing progress will be discarded.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRerollOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleRerollConfirm}>
              <RefreshCw className="mr-1.5 size-3.5" />
              Reroll
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirm dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete &ldquo;{brief.name}&rdquo;?</DialogTitle>
            <DialogDescription>
              This will permanently remove this hackathon and all associated
              agents, checkpoints, and artifacts.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteConfirm}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
