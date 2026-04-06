"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Convert from "ansi-to-html"
import { ArrowDown, Pause } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { LAYER_AGENTS } from "@/lib/types"
import type { AgentPhaseName, LogEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

const convert = new Convert({ fg: "#e4e4e7", bg: "transparent" })

const PHASE_COLORS: Record<AgentPhaseName, string> = {
  intelligence: "#60a5fa",
  strategy: "#a78bfa",
  design: "#f472b6",
  build: "#fbbf24",
  verify: "#34d399",
  polish: "#22d3ee",
  submission: "#fb923c",
  infra: "#a1a1aa",
}

function agentPhase(agentId: string): AgentPhaseName | undefined {
  for (const [phase, agents] of Object.entries(LAYER_AGENTS)) {
    if ((agents as readonly string[]).includes(agentId))
      return phase as AgentPhaseName
  }
  return undefined
}

const LEVEL_COLORS: Record<string, string> = {
  debug: "text-zinc-500",
  info: "text-zinc-300",
  warning: "text-yellow-400",
  error: "text-red-400",
  critical: "text-red-500 font-bold",
}

const MAX_LINES = 500

interface LogViewerProps {
  logs: LogEntry[]
  loading?: boolean
  onFilterChange?: (agent: string, level: string) => void
}

export function LogViewer({ logs, loading, onFilterChange }: LogViewerProps) {
  const [agentFilter, setAgentFilter] = useState("all")
  const [levelFilter, setLevelFilter] = useState("all")
  const [autoScroll, setAutoScroll] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => {
    let result = logs
    if (agentFilter !== "all")
      result = result.filter((l) => l.agent_id === agentFilter)
    if (levelFilter !== "all")
      result = result.filter((l) => l.level === levelFilter)
    return result.slice(-MAX_LINES)
  }, [logs, agentFilter, levelFilter])

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [filtered, autoScroll])

  const handleAgentChange = useCallback(
    (val: unknown) => {
      const v = String(val)
      setAgentFilter(v)
      onFilterChange?.(v, levelFilter)
    },
    [levelFilter, onFilterChange],
  )

  const handleLevelChange = useCallback(
    (val: unknown) => {
      const v = String(val)
      setLevelFilter(v)
      onFilterChange?.(agentFilter, v)
    },
    [agentFilter, onFilterChange],
  )

  const uniqueAgents = useMemo(() => {
    const set = new Set<string>()
    for (const l of logs) if (l.agent_id) set.add(l.agent_id)
    return Array.from(set).sort()
  }, [logs])

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border/50 p-2">
        <Select value={agentFilter} onValueChange={handleAgentChange}>
          <SelectTrigger size="sm" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Agents</SelectItem>
            {uniqueAgents.map((a) => (
              <SelectItem key={a} value={a}>
                {a.replace(/_/g, " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={levelFilter} onValueChange={handleLevelChange}>
          <SelectTrigger size="sm" className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Levels</SelectItem>
            <SelectItem value="debug">Debug</SelectItem>
            <SelectItem value="info">Info</SelectItem>
            <SelectItem value="warning">Warning</SelectItem>
            <SelectItem value="error">Error</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
          </SelectContent>
        </Select>
        {loading && (
          <span className="ml-auto animate-pulse text-xs text-muted-foreground">
            Streaming…
          </span>
        )}
      </div>

      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto bg-zinc-950 p-2 font-mono text-xs leading-5"
      >
        {filtered.map((log, i) => {
          const phase = log.agent_id ? agentPhase(log.agent_id) : undefined
          const agentColor = phase ? PHASE_COLORS[phase] : "#a1a1aa"

          return (
            <div key={i} className="flex gap-2 hover:bg-white/[0.02]">
              <span className="shrink-0 select-none text-zinc-600">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              {log.agent_id && (
                <span
                  className="shrink-0 select-none"
                  style={{ color: agentColor }}
                >
                  [{log.agent_id}]
                </span>
              )}
              <span
                className={cn("flex-1 break-all", LEVEL_COLORS[log.level])}
                dangerouslySetInnerHTML={{
                  __html: convert.toHtml(log.message),
                }}
              />
            </div>
          )
        })}
      </div>

      <Button
        size="icon-sm"
        variant={autoScroll ? "default" : "outline"}
        className="absolute bottom-4 right-4 z-10 rounded-full"
        onClick={() => {
          setAutoScroll((prev) => {
            if (prev === false && containerRef.current) {
              containerRef.current.scrollTop =
                containerRef.current.scrollHeight
            }
            return !prev
          })
        }}
      >
        {autoScroll ? (
          <Pause className="size-3.5" />
        ) : (
          <ArrowDown className="size-3.5" />
        )}
      </Button>
    </div>
  )
}
