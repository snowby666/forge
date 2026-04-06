"use client"

import {
  CheckCircle2,
  Circle,
  Loader2,
  Play,
  RotateCcw,
  XCircle,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { AgentPhaseName, AgentStatus } from "@/lib/types"
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

const PHASE_COLORS: Record<AgentPhaseName, string> = {
  intelligence: "text-blue-400",
  strategy: "text-violet-400",
  design: "text-pink-400",
  build: "text-amber-400",
  verify: "text-emerald-400",
  polish: "text-cyan-400",
  submission: "text-orange-400",
  infra: "text-zinc-400",
}

function prettify(id: string) {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

function StatusIcon({ status }: { status: AgentStatus["status"] }) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="size-3.5 text-emerald-500" />
    case "in-progress":
      return <Loader2 className="size-3.5 animate-spin text-yellow-500" />
    case "pending":
      return <Circle className="size-3.5 text-zinc-500" />
    case "failed":
      return <XCircle className="size-3.5 text-red-500" />
  }
}

function elapsed(updatedAt?: string) {
  if (!updatedAt) return null
  const ms = Date.now() - new Date(updatedAt).getTime()
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`
  return `${Math.round(ms / 3_600_000)}h`
}

interface AgentTimelineProps {
  agents: AgentStatus[]
  hackathonId: string
  onTrigger?: (agentId: string) => void
  onRestart?: (agentId: string) => void
}

export function AgentTimeline({
  agents,
  onTrigger,
  onRestart,
}: AgentTimelineProps) {
  const byPhase = new Map<AgentPhaseName, AgentStatus[]>()
  for (const a of agents) {
    const list = byPhase.get(a.phase) ?? []
    list.push(a)
    byPhase.set(a.phase, list)
  }

  return (
    <TooltipProvider>
      <div className="space-y-5">
        {PHASE_ORDER.map((phase) => {
          const phaseAgents = byPhase.get(phase)
          if (!phaseAgents?.length) return null

          return (
            <div key={phase}>
              <h3
                className={cn(
                  "mb-2 text-xs font-semibold uppercase tracking-wider",
                  PHASE_COLORS[phase],
                )}
              >
                {phase}
              </h3>
              <div className="flex flex-wrap gap-2">
                {phaseAgents.map((agent) => {
                  const time = elapsed(agent.updated_at)
                  return (
                    <Tooltip key={agent.agent_id}>
                      <TooltipTrigger
                        render={
                          <div className="group inline-flex items-center gap-1.5 rounded-md border border-border/40 bg-card/50 px-2.5 py-1.5 text-xs transition-colors hover:bg-accent/50" />
                        }
                      >
                        <StatusIcon status={agent.status} />
                        <span className="font-medium">
                          {prettify(agent.agent_id)}
                        </span>
                        {time && (
                          <span className="text-muted-foreground">{time}</span>
                        )}
                        {agent.status === "failed" && onRestart && (
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="ml-0.5 size-5 opacity-0 transition-opacity group-hover:opacity-100"
                            onClick={(e) => {
                              e.stopPropagation()
                              onRestart(agent.agent_id)
                            }}
                          >
                            <RotateCcw />
                          </Button>
                        )}
                        {(agent.status === "done" ||
                          agent.status === "failed") &&
                          onTrigger && (
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className="size-5 opacity-0 transition-opacity group-hover:opacity-100"
                              onClick={(e) => {
                                e.stopPropagation()
                                onTrigger(agent.agent_id)
                              }}
                            >
                              <Play />
                            </Button>
                          )}
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="font-medium">
                          {prettify(agent.agent_id)}
                        </p>
                        <p className="capitalize opacity-70">{agent.status}</p>
                        {agent.error && (
                          <p className="text-red-400">{agent.error}</p>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
