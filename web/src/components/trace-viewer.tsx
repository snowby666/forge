"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronRight,
  Copy,
  Download,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchEvents, fetchTraceSummary } from "@/lib/api";
import type { TraceSpan, TraceSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const OP_CONFIG: Record<string, { label: string; color: string; icon: string; bg: string }> = {
  llm:        { label: "LLM",      icon: "⚡", color: "text-blue-400",    bg: "bg-blue-500/10 border-blue-500/20" },
  mcp:        { label: "MCP",      icon: "🔌", color: "text-purple-400",  bg: "bg-purple-500/10 border-purple-500/20" },
  http:       { label: "HTTP",     icon: "🌐", color: "text-green-400",   bg: "bg-green-500/10 border-green-500/20" },
  file:       { label: "File",     icon: "📄", color: "text-amber-400",   bg: "bg-amber-500/10 border-amber-500/20" },
  redis:      { label: "Redis",    icon: "🗃️", color: "text-red-400",     bg: "bg-red-500/10 border-red-500/20" },
  subprocess: { label: "Process",  icon: "⚙️", color: "text-gray-400",    bg: "bg-gray-500/10 border-gray-500/20" },
  artifact:   { label: "Artifact", icon: "📦", color: "text-cyan-400",    bg: "bg-cyan-500/10 border-cyan-500/20" },
  daytona:    { label: "Sandbox",  icon: "🐳", color: "text-teal-400",    bg: "bg-teal-500/10 border-teal-500/20" },
  log:        { label: "Trace",    icon: "📝", color: "text-zinc-400",    bg: "bg-zinc-500/10 border-zinc-500/20" },
};

function formatElapsed(s: number): string {
  if (s >= 60) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s >= 1) return `${s.toFixed(1)}s`;
  if (s > 0) return `${Math.round(s * 1000)}ms`;
  return "";
}

function SummaryBar({ summary }: { summary: TraceSummary }) {
  const stats = [
    { label: "Total Ops", value: summary.total_spans, color: "text-white" },
    { label: "LLM Calls", value: summary.by_op?.llm || 0, color: "text-blue-400" },
    { label: "Tokens", value: summary.total_llm_tokens ? `${(summary.total_llm_tokens / 1000).toFixed(1)}k` : "0", color: "text-blue-300" },
    { label: "Cost", value: `$${summary.total_llm_cost_usd?.toFixed(2) || "0.00"}`, color: "text-emerald-400" },
    { label: "HTTP", value: summary.by_op?.http || 0, color: "text-green-400" },
    { label: "Files", value: summary.total_file_writes, color: "text-amber-400" },
    { label: "MCP", value: summary.by_op?.mcp || 0, color: "text-purple-400" },
    { label: "Errors", value: summary.error_count, color: summary.error_count > 0 ? "text-red-400" : "text-zinc-500" },
  ];

  return (
    <div className="grid grid-cols-4 md:grid-cols-8 gap-1.5">
      {stats.map((s) => (
        <div key={s.label} className="rounded-lg border border-zinc-800/60 bg-zinc-900/40 px-2 py-1.5 text-center">
          <div className={`font-mono text-sm font-bold ${s.color}`}>{s.value}</div>
          <div className="text-[9px] text-zinc-600 uppercase tracking-wider">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

function SpanRow({
  span,
  expanded,
  onToggle,
}: {
  span: TraceSpan;
  expanded: boolean;
  onToggle: () => void;
}) {
  const cfg = OP_CONFIG[span.op] || OP_CONFIG.subprocess;
  const ts = new Date(span.started_at).toLocaleTimeString();

  return (
    <div className="group border-b border-zinc-800/30 last:border-0">
      <button
        onClick={onToggle}
        className={cn(
          "w-full flex items-center gap-1.5 px-3 py-1.5 text-left transition-colors text-xs",
          "hover:bg-white/[0.02]",
          span.status === "error" && "bg-red-500/[0.03]",
        )}
      >
        <span className={cn(
          "inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-mono border shrink-0",
          cfg.bg, cfg.color,
        )}>
          {cfg.icon} {cfg.label}
        </span>

        <span className="text-zinc-600 font-mono text-[10px] w-[52px] shrink-0">{ts}</span>

        <span className="text-zinc-500 font-mono text-[10px] px-1 py-0.5 rounded bg-zinc-800/60 shrink-0 max-w-[90px] truncate">
          {span.agent_id}
        </span>

        <span className="truncate flex-1 font-mono text-[11px] text-zinc-300">
          {span.name}
        </span>

        {span.elapsed_s > 0 && (
          <span className="text-zinc-600 font-mono text-[10px] shrink-0">
            {formatElapsed(span.elapsed_s)}
          </span>
        )}

        {span.status === "error" && <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />}
        {span.status === "ok" && span.elapsed_s > 0 && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60 shrink-0" />}

        {(span.input || span.output || span.error) && (
          <ChevronRight className={cn(
            "size-3 text-zinc-600 shrink-0 transition-transform",
            expanded && "rotate-90",
          )} />
        )}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-4 py-3 bg-zinc-900/60 text-xs font-mono space-y-2 border-t border-zinc-800/30">
              <div className="flex flex-wrap gap-4">
                <div>
                  <span className="text-zinc-600">Started</span>{" "}
                  <span className="text-zinc-400">{span.started_at}</span>
                </div>
                {span.elapsed_s > 0 && (
                  <div>
                    <span className="text-zinc-600">Duration</span>{" "}
                    <span className="text-zinc-400">{formatElapsed(span.elapsed_s)}</span>
                  </div>
                )}
                {span.tags && Object.keys(span.tags).length > 0 && (
                  <div>
                    <span className="text-zinc-600">Tags</span>{" "}
                    <span className="text-zinc-500">{JSON.stringify(span.tags)}</span>
                  </div>
                )}
              </div>
              {span.input && Object.keys(span.input).length > 0 && (
                <div>
                  <div className="text-zinc-600 mb-1">Input</div>
                  <pre className="text-zinc-400 whitespace-pre-wrap break-words bg-zinc-950/80 rounded p-2 max-h-32 overflow-auto">
                    {JSON.stringify(span.input, null, 2)}
                  </pre>
                </div>
              )}
              {span.output && Object.keys(span.output).length > 0 && (
                <div>
                  <div className="text-zinc-600 mb-1">Output</div>
                  <pre className="text-zinc-400 whitespace-pre-wrap break-words bg-zinc-950/80 rounded p-2 max-h-32 overflow-auto">
                    {JSON.stringify(span.output, null, 2)}
                  </pre>
                </div>
              )}
              {span.error && (
                <div>
                  <div className="text-red-400 mb-1">Error</div>
                  <pre className="text-red-300 whitespace-pre-wrap break-words bg-red-950/30 rounded p-2 max-h-32 overflow-auto">
                    {span.error}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function TraceViewer({ hackathonId }: { hackathonId: string }) {
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [opFilter, setOpFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: summary } = useSWR(
    `/api/hackathon/${hackathonId}/traces/summary`,
    () => fetchTraceSummary(hackathonId),
    { refreshInterval: 10_000 },
  );

  const { data: eventData, isLoading } = useSWR(
    [`/api/hackathon/${hackathonId}/events`, agentFilter, opFilter],
    () => fetchEvents(hackathonId, {
      agent: agentFilter || undefined,
      limit: 2000,
    }),
    { refreshInterval: 10_000 },
  );

  const allSpans = useMemo(() => {
    const events = eventData?.events || [];
    const q = search.toLowerCase();
    return events.filter((span) => {
      if (opFilter && span.op !== opFilter) return false;
      if (q && !span.name?.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [eventData, opFilter, search]);

  const agents = summary ? Object.keys(summary.by_agent).sort() : [];
  const totalCount = allSpans.length;

  const handleCopyAll = useCallback(() => {
    const text = allSpans
      .map((s) => `${s.started_at} [${s.op}] ${s.agent_id} ${s.name}${s.elapsed_s ? ` (${formatElapsed(s.elapsed_s)})` : ""}`)
      .join("\n");
    navigator.clipboard.writeText(text);
  }, [allSpans]);

  const handleExport = useCallback(() => {
    const blob = new Blob([JSON.stringify(allSpans, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `traces-${hackathonId.slice(0, 12)}-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [allSpans, hackathonId]);

  return (
    <div className="space-y-3">
      {summary && <SummaryBar summary={summary} />}

      <div className="flex items-center gap-1.5 rounded-lg border border-zinc-800/60 bg-zinc-900/30 p-1.5">
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="rounded border border-zinc-700/60 bg-zinc-900 px-2 py-1 text-[11px] text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>{a.replace(/_/g, " ")}</option>
          ))}
        </select>

        <select
          value={opFilter}
          onChange={(e) => setOpFilter(e.target.value)}
          className="rounded border border-zinc-700/60 bg-zinc-900 px-2 py-1 text-[11px] text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        >
          <option value="">All Types</option>
          {Object.entries(OP_CONFIG).map(([k, v]) => (
            <option key={k} value={k}>{v.icon} {v.label}</option>
          ))}
        </select>

        {searchOpen ? (
          <div className="flex flex-1 items-center gap-1.5">
            <Search className="size-3 text-zinc-500 shrink-0" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter traces..."
              className="h-6 flex-1 border-0 bg-transparent text-xs text-zinc-300 placeholder:text-zinc-600 focus-visible:ring-0"
              autoFocus
            />
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-5 text-zinc-500"
              onClick={() => { setSearchOpen(false); setSearch(""); }}
            >
              <X className="size-3" />
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-6 text-zinc-500 hover:text-zinc-300"
            onClick={() => setSearchOpen(true)}
          >
            <Search className="size-3" />
          </Button>
        )}

        <div className="ml-auto flex items-center gap-1">
          <span className="text-[10px] text-zinc-600 font-mono mr-1">
            {totalCount} traces
          </span>
          <Button variant="ghost" size="icon-sm" className="size-6 text-zinc-500" onClick={handleCopyAll} title="Copy">
            <Copy className="size-3" />
          </Button>
          <Button variant="ghost" size="icon-sm" className="size-6 text-zinc-500" onClick={handleExport} title="Export JSON">
            <Download className="size-3" />
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/50 max-h-[600px] overflow-auto">
        {isLoading ? (
          <div className="p-8 text-center text-zinc-600 text-xs">Loading traces...</div>
        ) : allSpans.length === 0 ? (
          <div className="p-8 text-center text-zinc-600 text-xs">
            No traces recorded yet. Traces appear as agents execute operations.
          </div>
        ) : (
          allSpans.map((span) => (
            <SpanRow
              key={span.id}
              span={span}
              expanded={expandedId === span.id}
              onToggle={() => setExpandedId(expandedId === span.id ? null : span.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}
