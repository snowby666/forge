"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Convert from "ansi-to-html"
import {
  ArrowDown,
  Copy,
  Download,
  Pause,
  Search,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const convert = new Convert({
  fg: "#d4d4d8",
  bg: "transparent",
  newline: false,
  escapeXML: true,
})

type LineLevel = "error" | "warn" | "info" | "success" | "debug" | "plain"

const LEVEL_STYLES: Record<LineLevel, string> = {
  error: "text-red-400",
  warn: "text-amber-400",
  success: "text-emerald-400",
  info: "text-sky-400",
  debug: "text-zinc-500",
  plain: "text-zinc-300",
}

const LEVEL_GUTTER: Record<LineLevel, string> = {
  error: "bg-red-500/60",
  warn: "bg-amber-500/40",
  success: "bg-emerald-500/40",
  info: "bg-sky-500/20",
  debug: "bg-transparent",
  plain: "bg-transparent",
}

const ERROR_RE = /\b(error|exception|traceback|fatal|failed|panic)\b/i
const WARN_RE = /\b(warn|warning|deprecated|timeout)\b/i
const SUCCESS_RE = /\b(success|ready|done|complete|passed|stored|ok)\b/i
const INFO_RE = /\[(forge|info|daytona|scout)\]/i
const DEBUG_RE = /\b(debug)\b/i

function classifyLine(raw: string): LineLevel {
  if (ERROR_RE.test(raw)) return "error"
  if (WARN_RE.test(raw)) return "warn"
  if (SUCCESS_RE.test(raw)) return "success"
  if (INFO_RE.test(raw)) return "info"
  if (DEBUG_RE.test(raw)) return "debug"
  return "plain"
}

function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*m/g, "")
}

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

interface TerminalLogProps {
  lines: string[]
  maxHeight?: string
  className?: string
  showSearch?: boolean
  showToolbar?: boolean
  title?: string
}

export function TerminalLog({
  lines,
  maxHeight = "24rem",
  className,
  showSearch = true,
  showToolbar = true,
  title,
}: TerminalLogProps) {
  const [autoScroll, setAutoScroll] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [searchOpen, setSearchOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const parsed = useMemo(
    () =>
      lines.map((raw) => {
        const level = classifyLine(raw)
        const html = convert.toHtml(raw)
        return { raw, level, html }
      }),
    [lines],
  )

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return parsed
    const q = searchQuery.toLowerCase()
    return parsed.filter((l) => stripAnsi(l.raw).toLowerCase().includes(q))
  }, [parsed, searchQuery])

  const matchCount = searchQuery.trim()
    ? filtered.length
    : null

  const stats = useMemo(() => {
    let errors = 0
    let warns = 0
    for (const l of parsed) {
      if (l.level === "error") errors++
      else if (l.level === "warn") warns++
    }
    return { errors, warns, total: parsed.length }
  }, [parsed])

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [filtered.length, autoScroll])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    if (autoScroll && !atBottom) setAutoScroll(false)
  }, [autoScroll])

  const handleCopy = useCallback(() => {
    const text = filtered.map((l) => stripAnsi(l.raw)).join("\n")
    navigator.clipboard.writeText(text)
  }, [filtered])

  const handleDownload = useCallback(() => {
    const text = filtered.map((l) => stripAnsi(l.raw)).join("\n")
    const blob = new Blob([text], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${title ?? "log"}-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }, [filtered, title])

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950",
        className,
      )}
    >
      {showToolbar && (
        <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900/80 px-3 py-1.5">
          {/* Traffic-light dots */}
          <div className="flex gap-1.5 mr-2">
            <span className="size-2.5 rounded-full bg-red-500/70" />
            <span className="size-2.5 rounded-full bg-yellow-500/70" />
            <span className="size-2.5 rounded-full bg-green-500/70" />
          </div>

          {title && (
            <span className="text-[11px] font-medium text-zinc-400">
              {title}
            </span>
          )}

          <div className="ml-auto flex items-center gap-1.5 text-[10px] text-zinc-500">
            <span>{stats.total} lines</span>
            {stats.errors > 0 && (
              <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-red-400">
                {stats.errors} errors
              </span>
            )}
            {stats.warns > 0 && (
              <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-400">
                {stats.warns} warnings
              </span>
            )}
          </div>

          {showSearch && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-6 text-zinc-500 hover:text-zinc-300"
              onClick={() => {
                setSearchOpen((v) => !v)
                if (searchOpen) setSearchQuery("")
              }}
            >
              <Search className="size-3" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-6 text-zinc-500 hover:text-zinc-300"
            onClick={handleCopy}
            title="Copy to clipboard"
          >
            <Copy className="size-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-6 text-zinc-500 hover:text-zinc-300"
            onClick={handleDownload}
            title="Download log"
          >
            <Download className="size-3" />
          </Button>
        </div>
      )}

      {searchOpen && (
        <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900/50 px-3 py-1.5">
          <Search className="size-3 text-zinc-500" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter lines..."
            className="h-6 flex-1 border-0 bg-transparent text-xs text-zinc-300 placeholder:text-zinc-600 focus-visible:ring-0"
            autoFocus
          />
          {matchCount !== null && (
            <span className="text-[10px] text-zinc-500">
              {matchCount} match{matchCount !== 1 ? "es" : ""}
            </span>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-5 text-zinc-500 hover:text-zinc-300"
            onClick={() => {
              setSearchOpen(false)
              setSearchQuery("")
            }}
          >
            <X className="size-3" />
          </Button>
        </div>
      )}

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="overflow-y-auto font-mono text-[12px] leading-[1.6]"
        style={{ maxHeight }}
      >
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-xs text-zinc-600">
            {lines.length === 0
              ? "No output yet..."
              : "No matching lines"}
          </div>
        ) : (
          filtered.map((line, i) => {
            const html = highlightSearch(line.html, searchQuery)
            return (
              <div
                key={i}
                className={cn(
                  "group flex hover:bg-white/[0.02]",
                  line.level === "error" && "bg-red-500/[0.03]",
                )}
              >
                {/* Level gutter indicator */}
                <span
                  className={cn(
                    "w-[3px] shrink-0",
                    LEVEL_GUTTER[line.level],
                  )}
                />
                {/* Line number */}
                <span className="w-10 shrink-0 select-none py-px pr-3 text-right text-zinc-700 tabular-nums">
                  {i + 1}
                </span>
                {/* Content */}
                <span
                  className={cn(
                    "min-w-0 flex-1 break-all py-px pr-3",
                    LEVEL_STYLES[line.level],
                  )}
                  dangerouslySetInnerHTML={{ __html: html }}
                />
              </div>
            )
          })
        )}
      </div>

      {/* Scroll-to-bottom FAB */}
      {!autoScroll && filtered.length > 20 && (
        <div className="absolute bottom-3 right-5">
          <Button
            size="icon-sm"
            variant="outline"
            className="rounded-full border-zinc-700 bg-zinc-900 shadow-lg"
            onClick={() => {
              setAutoScroll(true)
              if (containerRef.current)
                containerRef.current.scrollTop =
                  containerRef.current.scrollHeight
            }}
          >
            <ArrowDown className="size-3.5" />
          </Button>
        </div>
      )}
    </div>
  )
}
