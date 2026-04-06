"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Convert from "ansi-to-html"
import { AnimatePresence, motion } from "framer-motion"
import {
  ArrowDown,
  ChevronRight,
  Download,
  Pause,
  Search,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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

function highlightSearch(html: string, query: string): string {
  if (!query) return html
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const regex = new RegExp(escaped, "gi")
  return html
    .split(/(<[^>]*>)/)
    .map((part) =>
      part.startsWith("<")
        ? part
        : part.replace(
            regex,
            '<mark class="bg-yellow-500/30 text-yellow-200 rounded-sm px-0.5">$&</mark>',
          ),
    )
    .join("")
}

function formatDelta(ms: number): string {
  if (ms < 1000) return `+${ms}ms`
  if (ms < 60_000) return `+${(ms / 1000).toFixed(1)}s`
  return `+${(ms / 60_000).toFixed(1)}m`
}

function formatAvgInterval(logs: { timestamp: string }[]): string {
  if (logs.length < 2) return "—"
  const first = new Date(logs[0].timestamp).getTime()
  const last = new Date(logs[logs.length - 1].timestamp).getTime()
  const avg = (last - first) / (logs.length - 1)
  if (avg < 1000) return `${Math.round(avg)}ms`
  if (avg < 60_000) return `${(avg / 1000).toFixed(1)}s`
  return `${(avg / 60_000).toFixed(1)}m`
}

interface LogViewerProps {
  logs: LogEntry[]
  loading?: boolean
  onFilterChange?: (agent: string, level: string) => void
}

export function LogViewer({ logs, loading, onFilterChange }: LogViewerProps) {
  const [agentFilter, setAgentFilter] = useState("all")
  const [levelFilter, setLevelFilter] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")
  const [autoScroll, setAutoScroll] = useState(true)
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())
  const containerRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => {
    let result = logs
    if (agentFilter !== "all")
      result = result.filter((l) => l.agent_id === agentFilter)
    if (levelFilter !== "all")
      result = result.filter((l) => l.level === levelFilter)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter((l) => l.message.toLowerCase().includes(q))
    }
    return result.slice(-MAX_LINES)
  }, [logs, agentFilter, levelFilter, searchQuery])

  const stats = useMemo(
    () => ({
      total: filtered.length,
      errors: filtered.filter(
        (l) => l.level === "error" || l.level === "critical",
      ).length,
      warnings: filtered.filter((l) => l.level === "warning").length,
      avgInterval: formatAvgInterval(filtered),
    }),
    [filtered],
  )

  useEffect(() => {
    if (autoScroll && containerRef.current)
      containerRef.current.scrollTop = containerRef.current.scrollHeight
  }, [filtered, autoScroll])

  const handleAgentChange = useCallback(
    (val: string | null) => {
      const v = val ?? "all"
      setAgentFilter(v)
      onFilterChange?.(v, levelFilter)
    },
    [levelFilter, onFilterChange],
  )

  const handleLevelChange = useCallback(
    (val: string | null) => {
      const v = val ?? "all"
      setLevelFilter(v)
      onFilterChange?.(agentFilter, v)
    },
    [agentFilter, onFilterChange],
  )

  const handleAgentClick = useCallback(
    (agentId: string) => {
      setAgentFilter(agentId)
      onFilterChange?.(agentId, levelFilter)
    },
    [levelFilter, onFilterChange],
  )

  const toggleRow = useCallback((index: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }, [])

  const uniqueAgents = useMemo(() => {
    const set = new Set<string>()
    for (const l of logs) if (l.agent_id) set.add(l.agent_id)
    return Array.from(set).sort()
  }, [logs])

  const exportLogs = useCallback(() => {
    const text = filtered
      .map((l) => {
        const ts = new Date(l.timestamp).toISOString()
        const agent = l.agent_id ? ` [${l.agent_id}]` : ""
        const data = l.data ? ` ${JSON.stringify(l.data)}` : ""
        return `${ts} ${l.level.toUpperCase()}${agent} ${l.message}${data}`
      })
      .join("\n")
    const blob = new Blob([text], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `logs-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }, [filtered])

  const timelineData = useMemo(() => {
    if (logs.length === 0) return null
    const spans = new Map<
      string,
      { start: number; end: number; phase: AgentPhaseName | undefined }
    >()
    let globalStart = Infinity
    let globalEnd = -Infinity

    for (const log of logs) {
      if (!log.agent_id) continue
      const ts = new Date(log.timestamp).getTime()
      if (ts < globalStart) globalStart = ts
      if (ts > globalEnd) globalEnd = ts

      const existing = spans.get(log.agent_id)
      if (existing) {
        existing.start = Math.min(existing.start, ts)
        existing.end = Math.max(existing.end, ts)
      } else {
        spans.set(log.agent_id, {
          start: ts,
          end: ts,
          phase: agentPhase(log.agent_id),
        })
      }
    }

    const range = globalEnd - globalStart
    if (range <= 0) return null

    return Array.from(spans.entries()).map(([id, s]) => ({
      id,
      phase: s.phase,
      left: ((s.start - globalStart) / range) * 100,
      width: Math.max(((s.end - s.start) / range) * 100, 0.5),
    }))
  }, [logs])

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/50 p-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search logs…"
            className="h-7 pl-7 text-xs"
          />
          {searchQuery && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">
              {filtered.length} found
            </span>
          )}
        </div>
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
        <Button variant="outline" size="sm" onClick={exportLogs}>
          <Download className="size-3.5" />
          Export
        </Button>
        {loading && (
          <span className="animate-pulse text-xs text-muted-foreground">
            Streaming…
          </span>
        )}
      </div>

      <div className="flex items-center gap-4 border-b border-border/50 px-3 py-1.5 text-xs text-muted-foreground">
        <span>
          Total{" "}
          <span className="font-medium text-foreground">{stats.total}</span>
        </span>
        <span>
          Errors{" "}
          <span className="font-medium text-red-400">{stats.errors}</span>
        </span>
        <span>
          Warnings{" "}
          <span className="font-medium text-yellow-400">{stats.warnings}</span>
        </span>
        <span>
          Avg interval{" "}
          <span className="font-medium text-foreground">
            {stats.avgInterval}
          </span>
        </span>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={containerRef}
          className="h-full overflow-y-auto bg-zinc-950 font-mono text-xs leading-5"
        >
          {filtered.map((log, i) => {
            const phase = log.agent_id ? agentPhase(log.agent_id) : undefined
            const color = phase ? PHASE_COLORS[phase] : "#a1a1aa"
            const prevTs =
              i > 0 ? new Date(filtered[i - 1].timestamp).getTime() : null
            const curTs = new Date(log.timestamp).getTime()
            const delta = prevTs !== null ? curTs - prevTs : 0
            const expanded = expandedRows.has(i)
            const html = highlightSearch(
              convert.toHtml(log.message),
              searchQuery,
            )

            return (
              <div key={i} className="group">
                <div className="flex hover:bg-white/[0.02]">
                  <span className="w-10 shrink-0 select-none border-r border-zinc-800 pr-2 text-right text-zinc-600">
                    {i + 1}
                  </span>
                  <span
                    className="w-16 shrink-0 select-none pl-2 text-zinc-600"
                    title={new Date(log.timestamp).toLocaleString()}
                  >
                    {i === 0 ? "0s" : formatDelta(delta)}
                  </span>
                  {log.agent_id && (
                    <button
                      onClick={() => handleAgentClick(log.agent_id!)}
                      className="shrink-0 select-none hover:underline"
                      style={{ color }}
                    >
                      [{log.agent_id}]
                    </button>
                  )}
                  <span
                    className={cn(
                      "flex-1 break-all px-2",
                      LEVEL_COLORS[log.level],
                    )}
                    dangerouslySetInnerHTML={{ __html: html }}
                  />
                  {log.data && (
                    <button
                      onClick={() => toggleRow(i)}
                      className="shrink-0 px-1 text-zinc-500 hover:text-zinc-300"
                    >
                      <ChevronRight
                        className={cn(
                          "size-3 transition-transform",
                          expanded && "rotate-90",
                        )}
                      />
                    </button>
                  )}
                </div>
                <AnimatePresence initial={false}>
                  {expanded && log.data && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.15 }}
                      className="overflow-hidden"
                    >
                      <pre className="ml-10 border-l border-zinc-800 bg-zinc-900/50 py-1 pl-4 text-[11px] leading-relaxed text-zinc-400">
                        {JSON.stringify(log.data, null, 2)}
                      </pre>
                    </motion.div>
                  )}
                </AnimatePresence>
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
              if (!prev && containerRef.current)
                containerRef.current.scrollTop =
                  containerRef.current.scrollHeight
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

      {timelineData && timelineData.length > 0 && (
        <div className="border-t border-border/50 bg-zinc-950 px-3 py-2">
          <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Agent Timeline
          </p>
          <div className="space-y-1">
            {timelineData.map((agent) => (
              <div key={agent.id} className="flex items-center gap-2">
                <span className="w-28 truncate text-[10px] text-zinc-500">
                  {agent.id.replace(/_/g, " ")}
                </span>
                <div className="relative h-2 flex-1 rounded-full bg-zinc-800">
                  <div
                    className="absolute h-full rounded-full opacity-80"
                    style={{
                      left: `${agent.left}%`,
                      width: `${agent.width}%`,
                      backgroundColor: agent.phase
                        ? PHASE_COLORS[agent.phase]
                        : "#a1a1aa",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
