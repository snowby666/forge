"use client"

import { useCallback, useMemo, useState } from "react"
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  Loader2,
  Play,
  RotateCcw,
  ScrollText,
  XCircle,
} from "lucide-react"
import { AnimatePresence, motion } from "framer-motion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type {
  AgentPhaseName,
  AgentStatus,
  AgentStatusValue,
} from "@/lib/types"
import { fetchLogs, triggerAgent, restartAgent } from "@/lib/api"
import { cn } from "@/lib/utils"

const PHASE_ORDER: AgentPhaseName[] = [
  "intelligence",
  "strategy",
  "design",
  "build",
  "verify",
  "polish",
  "submission",
  "infra",
]

const PHASE_META: Record<
  AgentPhaseName,
  { label: string; color: string; bg: string; bar: string; ring: string }
> = {
  intelligence: {
    label: "Intelligence",
    color: "text-blue-400",
    bg: "bg-blue-500/15",
    bar: "bg-blue-500",
    ring: "ring-blue-500/30",
  },
  strategy: {
    label: "Strategy",
    color: "text-violet-400",
    bg: "bg-violet-500/15",
    bar: "bg-violet-500",
    ring: "ring-violet-500/30",
  },
  design: {
    label: "Design",
    color: "text-pink-400",
    bg: "bg-pink-500/15",
    bar: "bg-pink-500",
    ring: "ring-pink-500/30",
  },
  build: {
    label: "Build",
    color: "text-amber-400",
    bg: "bg-amber-500/15",
    bar: "bg-amber-500",
    ring: "ring-amber-500/30",
  },
  verify: {
    label: "Verify",
    color: "text-emerald-400",
    bg: "bg-emerald-500/15",
    bar: "bg-emerald-500",
    ring: "ring-emerald-500/30",
  },
  polish: {
    label: "Polish",
    color: "text-cyan-400",
    bg: "bg-cyan-500/15",
    bar: "bg-cyan-500",
    ring: "ring-cyan-500/30",
  },
  submission: {
    label: "Submission",
    color: "text-orange-400",
    bg: "bg-orange-500/15",
    bar: "bg-orange-500",
    ring: "ring-orange-500/30",
  },
  infra: {
    label: "Infrastructure",
    color: "text-zinc-400",
    bg: "bg-zinc-500/15",
    bar: "bg-zinc-500",
    ring: "ring-zinc-500/30",
  },
}

const STATUS_COLORS: Record<AgentStatusValue, string> = {
  done: "bg-emerald-500",
  "in-progress": "bg-yellow-500",
  pending: "bg-zinc-600",
  failed: "bg-red-500",
}

function prettify(id: string) {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

function elapsedMs(updatedAt?: string): number {
  if (!updatedAt) return 0
  return Math.max(0, Date.now() - new Date(updatedAt).getTime())
}

function formatElapsed(ms: number): string {
  if (ms <= 0) return "—"
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rs = s % 60
  if (m < 60) return rs > 0 ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h}h ${rm}m` : `${h}h`
}

function StatusIcon({ status }: { status: AgentStatusValue }) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="size-4 text-emerald-500" />
    case "in-progress":
      return <Loader2 className="size-4 animate-spin text-yellow-500" />
    case "pending":
      return <Circle className="size-4 text-zinc-500" />
    case "failed":
      return <XCircle className="size-4 text-red-500" />
  }
}

function PhaseStatusIcon({ agents }: { agents: AgentStatus[] }) {
  const hasFailed = agents.some((a) => a.status === "failed")
  const hasInProgress = agents.some((a) => a.status === "in-progress")
  const allDone = agents.every((a) => a.status === "done")

  if (allDone)
    return <CheckCircle2 className="size-5 text-emerald-500" />
  if (hasFailed)
    return <XCircle className="size-5 text-red-500" />
  if (hasInProgress)
    return <Loader2 className="size-5 animate-spin text-yellow-500" />
  return <Circle className="size-5 text-zinc-500" />
}

function derivePhaseStatus(agents: AgentStatus[]): AgentStatusValue {
  if (agents.every((a) => a.status === "done")) return "done"
  if (agents.some((a) => a.status === "failed")) return "failed"
  if (agents.some((a) => a.status === "in-progress")) return "in-progress"
  return "pending"
}

// ── Gantt Overview ─────────────────────────────────────────

function GanttOverview({ phases }: { phases: Map<AgentPhaseName, AgentStatus[]> }) {
  const rows: { agent: AgentStatus; phase: AgentPhaseName }[] = []
  for (const phase of PHASE_ORDER) {
    const agents = phases.get(phase)
    if (agents) {
      for (const a of agents) rows.push({ agent: a, phase })
    }
  }
  if (rows.length === 0) return null

  const maxMs = Math.max(
    ...rows.map((r) => elapsedMs(r.agent.updated_at)),
    1,
  )

  return (
    <div className="rounded-lg border border-border/40 bg-card/30 p-3">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Pipeline Overview
      </p>
      <div className="flex flex-col gap-[3px]">
        {rows.map(({ agent, phase }) => {
          const ms = elapsedMs(agent.updated_at)
          const pct = Math.max(ms / maxMs * 100, agent.status === "pending" ? 0 : 4)
          return (
            <Tooltip key={agent.agent_id}>
              <TooltipTrigger
                render={<div className="flex items-center gap-2" />}
              >
                <span className="w-[100px] truncate text-[10px] text-muted-foreground">
                  {prettify(agent.agent_id)}
                </span>
                <div className="relative h-[6px] flex-1 rounded-full bg-border/30">
                  <motion.div
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full",
                      STATUS_COLORS[agent.status],
                    )}
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                  />
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">
                <p className="font-medium">{prettify(agent.agent_id)}</p>
                <p className="capitalize text-muted-foreground">
                  {PHASE_META[phase].label} · {agent.status}
                </p>
                {ms > 0 && <p>{formatElapsed(ms)}</p>}
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </div>
  )
}

// ── Agent Row ──────────────────────────────────────────────

function AgentRow({
  agent,
  phase,
  maxMs,
  hackathonId,
  onTrigger,
  onRestart,
}: {
  agent: AgentStatus
  phase: AgentPhaseName
  maxMs: number
  hackathonId: string
  onTrigger?: (agentId: string) => void
  onRestart?: (agentId: string) => void
}) {
  const [showError, setShowError] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [loadingLogs, setLoadingLogs] = useState(false)

  const ms = elapsedMs(agent.updated_at)
  const pct = maxMs > 0 ? Math.max((ms / maxMs) * 100, agent.status === "pending" ? 0 : 6) : 0
  const meta = PHASE_META[phase]

  const handleViewLogs = useCallback(async () => {
    if (showLogs) {
      setShowLogs(false)
      return
    }
    setLoadingLogs(true)
    try {
      const entries = await fetchLogs(hackathonId)
      const filtered = entries
        .filter((l) => l.agent_id === agent.agent_id)
        .map(
          (l) =>
            `[${new Date(l.timestamp).toLocaleTimeString()}] ${l.level.toUpperCase()} ${l.message}`,
        )
      setLogs(filtered.length ? filtered : ["No logs found for this agent."])
    } catch {
      setLogs(["Failed to load logs."])
    } finally {
      setLoadingLogs(false)
      setShowLogs(true)
    }
  }, [showLogs, hackathonId, agent.agent_id])

  return (
    <div className="group/row">
      <div className="flex items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-muted/30">
        <StatusIcon status={agent.status} />

        <span className="min-w-[140px] text-sm font-medium">
          {prettify(agent.agent_id)}
        </span>

        <div className="flex flex-1 items-center gap-2">
          <div className="relative h-2 flex-1 rounded-full bg-border/30">
            <motion.div
              className={cn("absolute inset-y-0 left-0 rounded-full", meta.bar)}
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            />
          </div>
          <span className="w-[60px] text-right text-xs tabular-nums text-muted-foreground">
            {ms > 0 ? formatElapsed(ms) : "—"}
          </span>
        </div>

        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover/row:opacity-100">
          {onTrigger && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => onTrigger(agent.agent_id)}
                  />
                }
              >
                <Play className="size-3" />
              </TooltipTrigger>
              <TooltipContent>Trigger agent</TooltipContent>
            </Tooltip>
          )}
          {onRestart && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => onRestart(agent.agent_id)}
                  />
                }
              >
                <RotateCcw className="size-3" />
              </TooltipTrigger>
              <TooltipContent>Restart agent</TooltipContent>
            </Tooltip>
          )}
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={handleViewLogs}
                />
              }
            >
              {loadingLogs ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <ScrollText className="size-3" />
              )}
            </TooltipTrigger>
            <TooltipContent>View logs</TooltipContent>
          </Tooltip>
        </div>
      </div>

      <AnimatePresence>
        {agent.status === "failed" && agent.error && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <button
              onClick={() => setShowError((v) => !v)}
              className="ml-9 flex items-center gap-1 text-xs text-red-400 hover:text-red-300"
            >
              <ChevronDown
                className={cn(
                  "size-3 transition-transform",
                  showError && "rotate-180",
                )}
              />
              Error details
            </button>
            <AnimatePresence>
              {showError && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="overflow-hidden"
                >
                  <pre className="ml-9 mt-1 rounded-md bg-red-500/10 p-2.5 text-xs leading-relaxed text-red-300 ring-1 ring-red-500/20">
                    {agent.error}
                  </pre>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showLogs && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <pre className="ml-9 mt-1 max-h-48 overflow-auto rounded-md bg-muted/40 p-2.5 text-xs leading-relaxed text-muted-foreground ring-1 ring-border/40">
              {logs.join("\n") || "Loading..."}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Phase Section ──────────────────────────────────────────

function PhaseSection({
  phase,
  agents,
  isLast,
  hackathonId,
  onTrigger,
  onRestart,
}: {
  phase: AgentPhaseName
  agents: AgentStatus[]
  isLast: boolean
  hackathonId: string
  onTrigger?: (agentId: string) => void
  onRestart?: (agentId: string) => void
}) {
  const [expanded, setExpanded] = useState(true)
  const meta = PHASE_META[phase]
  const doneCount = agents.filter((a) => a.status === "done").length
  const phasePct = agents.length > 0 ? (doneCount / agents.length) * 100 : 0
  const phaseStatus = derivePhaseStatus(agents)

  const maxMs = Math.max(...agents.map((a) => elapsedMs(a.updated_at)), 1)
  const pendingAgents = agents.filter((a) => a.status === "pending")
  const failedAgents = agents.filter((a) => a.status === "failed")

  const handleRunPhase = useCallback(() => {
    for (const a of pendingAgents) {
      triggerAgent(hackathonId, a.agent_id)
      onTrigger?.(a.agent_id)
    }
  }, [pendingAgents, hackathonId, onTrigger])

  const handleRetryFailed = useCallback(() => {
    for (const a of failedAgents) {
      restartAgent(hackathonId, a.agent_id)
      onRestart?.(a.agent_id)
    }
  }, [failedAgents, hackathonId, onRestart])

  return (
    <div className="relative flex gap-3">
      {/* Timeline connector */}
      <div className="flex flex-col items-center pt-1">
        <div
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-full ring-2",
            phaseStatus === "done" && "bg-emerald-500/15 ring-emerald-500/40",
            phaseStatus === "in-progress" && "bg-yellow-500/15 ring-yellow-500/40",
            phaseStatus === "failed" && "bg-red-500/15 ring-red-500/40",
            phaseStatus === "pending" && "bg-zinc-500/15 ring-zinc-500/30",
          )}
        >
          <PhaseStatusIcon agents={agents} />
        </div>
        {!isLast && (
          <div className="w-px flex-1 bg-border/40" />
        )}
      </div>

      {/* Phase content */}
      <div className="flex-1 pb-6">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center gap-3 rounded-lg p-1.5 transition-colors hover:bg-muted/20"
        >
          <div className="flex flex-1 items-center gap-2.5">
            <span className={cn("text-sm font-semibold", meta.color)}>
              {meta.label}
            </span>
            <Badge
              variant="secondary"
              className={cn(
                "h-5 text-[11px] tabular-nums",
                meta.bg,
                meta.color,
              )}
            >
              {doneCount}/{agents.length}
            </Badge>
            <div className="hidden h-1.5 flex-1 rounded-full bg-border/30 sm:block">
              <motion.div
                className={cn("h-full rounded-full", meta.bar)}
                initial={{ width: 0 }}
                animate={{ width: `${phasePct}%` }}
                transition={{ duration: 0.6, ease: "easeOut" }}
              />
            </div>
          </div>

          <div className="flex items-center gap-1">
            {pendingAgents.length > 0 && (
              <Button
                variant="ghost"
                size="xs"
                className="text-xs"
                onClick={(e) => {
                  e.stopPropagation()
                  handleRunPhase()
                }}
              >
                <Play className="size-3" />
                Run Phase
              </Button>
            )}
            {failedAgents.length > 0 && (
              <Button
                variant="ghost"
                size="xs"
                className="text-xs text-red-400 hover:text-red-300"
                onClick={(e) => {
                  e.stopPropagation()
                  handleRetryFailed()
                }}
              >
                <RotateCcw className="size-3" />
                Retry Failed
              </Button>
            )}
            <ChevronDown
              className={cn(
                "size-4 text-muted-foreground transition-transform duration-200",
                expanded && "rotate-180",
              )}
            />
          </div>
        </button>

        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: "easeInOut" }}
              className="overflow-hidden"
            >
              <div className="mt-1 space-y-0.5">
                {agents.map((agent) => (
                  <AgentRow
                    key={agent.agent_id}
                    agent={agent}
                    phase={phase}
                    maxMs={maxMs}
                    hackathonId={hackathonId}
                    onTrigger={onTrigger}
                    onRestart={onRestart}
                  />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────

interface AgentTimelineProps {
  agents: AgentStatus[]
  hackathonId: string
  onTrigger?: (agentId: string) => void
  onRestart?: (agentId: string) => void
}

export function AgentTimeline({
  agents,
  hackathonId,
  onTrigger,
  onRestart,
}: AgentTimelineProps) {
  const byPhase = useMemo(() => {
    const map = new Map<AgentPhaseName, AgentStatus[]>()
    for (const a of agents) {
      const list = map.get(a.phase) ?? []
      list.push(a)
      map.set(a.phase, list)
    }
    return map
  }, [agents])

  const activePhases = useMemo(
    () => PHASE_ORDER.filter((p) => byPhase.has(p)),
    [byPhase],
  )

  if (agents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Circle className="mb-2 size-8 opacity-30" />
        <p className="text-sm">No agents registered</p>
      </div>
    )
  }

  return (
    <TooltipProvider>
      <div className="space-y-4">
        <GanttOverview phases={byPhase} />

        <div className="flex flex-col">
          {activePhases.map((phase, i) => (
            <PhaseSection
              key={phase}
              phase={phase}
              agents={byPhase.get(phase)!}
              isLast={i === activePhases.length - 1}
              hackathonId={hackathonId}
              onTrigger={onTrigger}
              onRestart={onRestart}
            />
          ))}
        </div>
      </div>
    </TooltipProvider>
  )
}
