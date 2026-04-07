"use client";

import { useState } from "react";
import useSWR from "swr";
import { motion, AnimatePresence } from "framer-motion";
import { fetchTraces, fetchTraceSummary, fetchEvents } from "@/lib/api";
import type { TraceSpan, TraceSummary, TraceOp, UnifiedEvent, LogEntry } from "@/lib/types";

const OP_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  llm: { label: "LLM", color: "bg-blue-500/20 text-blue-400 border-blue-500/30", icon: "⚡" },
  mcp: { label: "MCP", color: "bg-purple-500/20 text-purple-400 border-purple-500/30", icon: "🔌" },
  http: { label: "HTTP", color: "bg-green-500/20 text-green-400 border-green-500/30", icon: "🌐" },
  file: { label: "File", color: "bg-amber-500/20 text-amber-400 border-amber-500/30", icon: "📄" },
  redis: { label: "Redis", color: "bg-red-500/20 text-red-400 border-red-500/30", icon: "🗃️" },
  subprocess: { label: "Process", color: "bg-gray-500/20 text-gray-400 border-gray-500/30", icon: "⚙️" },
  artifact: { label: "Artifact", color: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30", icon: "📦" },
};

const LOG_LEVEL_COLORS: Record<string, string> = {
  info: "text-sky-400",
  warning: "text-amber-400",
  error: "text-red-400",
  critical: "text-red-500",
  debug: "text-zinc-500",
};

function formatElapsed(s: number): string {
  if (s >= 60) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s >= 1) return `${s.toFixed(1)}s`;
  return `${Math.round(s * 1000)}ms`;
}

function SummaryBar({ summary }: { summary: TraceSummary }) {
  const stats = [
    { label: "Total Ops", value: summary.total_spans, color: "text-white" },
    { label: "LLM Calls", value: summary.by_op?.llm || 0, color: "text-blue-400" },
    { label: "LLM Tokens", value: summary.total_llm_tokens?.toLocaleString() || "0", color: "text-blue-300" },
    { label: "Cost", value: `$${summary.total_llm_cost_usd?.toFixed(2) || "0.00"}`, color: "text-emerald-400" },
    { label: "MCP", value: summary.by_op?.mcp || 0, color: "text-purple-400" },
    { label: "HTTP", value: summary.by_op?.http || 0, color: "text-green-400" },
    { label: "Files", value: summary.total_file_writes, color: "text-amber-400" },
    { label: "Errors", value: summary.error_count, color: summary.error_count > 0 ? "text-red-400" : "text-zinc-500" },
  ];

  return (
    <div className="grid grid-cols-4 md:grid-cols-8 gap-2 mb-4">
      {stats.map((s) => (
        <div key={s.label} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-2 text-center">
          <div className={`font-mono text-sm font-bold ${s.color}`}>{s.value}</div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wider">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

function SpanRow({ span, expanded, onToggle }: { span: TraceSpan; expanded: boolean; onToggle: () => void }) {
  const cfg = OP_CONFIG[span.op] || OP_CONFIG.subprocess;
  const ts = new Date(span.started_at).toLocaleTimeString();

  return (
    <div className="border-b border-zinc-800/50 last:border-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-zinc-800/30 transition-colors text-sm"
      >
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono border ${cfg.color}`}>
          {cfg.icon} {cfg.label}
        </span>
        <span className="text-zinc-500 font-mono text-xs w-16 shrink-0">{ts}</span>
        <span className="text-zinc-400 font-mono text-xs px-1.5 py-0.5 rounded bg-zinc-800 shrink-0">
          {span.agent_id}
        </span>
        <span className="text-zinc-200 truncate flex-1 font-mono text-xs">{span.name}</span>
        <span className="text-zinc-500 font-mono text-xs shrink-0">{formatElapsed(span.elapsed_s)}</span>
        {span.status === "error" && (
          <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
        )}
        {span.status === "ok" && (
          <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
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
            <div className="px-4 py-3 bg-zinc-900/80 text-xs font-mono space-y-2 border-t border-zinc-800/50">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-zinc-500 mb-1">Started</div>
                  <div className="text-zinc-300">{span.started_at}</div>
                </div>
                <div>
                  <div className="text-zinc-500 mb-1">Duration</div>
                  <div className="text-zinc-300">{formatElapsed(span.elapsed_s)}</div>
                </div>
              </div>
              {span.input && Object.keys(span.input).length > 0 && (
                <div>
                  <div className="text-zinc-500 mb-1">Input</div>
                  <pre className="text-zinc-300 whitespace-pre-wrap break-words bg-zinc-950 rounded p-2 max-h-40 overflow-auto">
                    {JSON.stringify(span.input, null, 2)}
                  </pre>
                </div>
              )}
              {span.output && Object.keys(span.output).length > 0 && (
                <div>
                  <div className="text-zinc-500 mb-1">Output</div>
                  <pre className="text-zinc-300 whitespace-pre-wrap break-words bg-zinc-950 rounded p-2 max-h-40 overflow-auto">
                    {JSON.stringify(span.output, null, 2)}
                  </pre>
                </div>
              )}
              {span.error && (
                <div>
                  <div className="text-red-400 mb-1">Error</div>
                  <pre className="text-red-300 whitespace-pre-wrap break-words bg-red-950/30 rounded p-2 max-h-40 overflow-auto">
                    {span.error}
                  </pre>
                </div>
              )}
              {span.tags && Object.keys(span.tags).length > 0 && (
                <div>
                  <div className="text-zinc-500 mb-1">Tags</div>
                  <pre className="text-zinc-400 whitespace-pre-wrap break-words">{JSON.stringify(span.tags, null, 2)}</pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function LogRow({ log }: { log: LogEntry }) {
  const ts = new Date(log.timestamp).toLocaleTimeString();
  const levelColor = LOG_LEVEL_COLORS[log.level] || "text-zinc-400";
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-sm border-b border-zinc-800/30 bg-zinc-900/30">
      <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono border bg-zinc-700/20 text-zinc-400 border-zinc-600/30">
        LOG
      </span>
      <span className="text-[10px] text-zinc-600 font-mono w-16 shrink-0">{ts}</span>
      <span className="text-zinc-500 text-xs w-24 shrink-0 truncate">{log.agent_id || "system"}</span>
      <span className={`text-[10px] font-mono uppercase ${levelColor} w-12 shrink-0`}>{log.level}</span>
      <span className="text-zinc-300 text-xs truncate flex-1">{log.message}</span>
    </div>
  );
}

export default function TraceViewer({ hackathonId }: { hackathonId: string }) {
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [opFilter, setOpFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(true);

  const { data: summary } = useSWR(
    `/api/hackathon/${hackathonId}/traces/summary`,
    () => fetchTraceSummary(hackathonId),
    { refreshInterval: 10_000 },
  );

  const { data: eventData, isLoading } = useSWR(
    [`/api/hackathon/${hackathonId}/events`, agentFilter, showLogs],
    () => fetchEvents(hackathonId, {
      agent: agentFilter || undefined,
      limit: 2000,
    }),
    { refreshInterval: 10_000 },
  );

  const allEvents = (eventData?.events || []).filter((ev) => {
    if (ev.kind === "span") {
      if (opFilter && (ev as TraceSpan).op !== opFilter) return false;
      if (search && !(ev as TraceSpan).name.toLowerCase().includes(search.toLowerCase())) return false;
    }
    if (ev.kind === "log" && !showLogs) return false;
    if (ev.kind === "log" && search) {
      if (!(ev as LogEntry).message?.toLowerCase().includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const agents = summary ? Object.keys(summary.by_agent).sort() : [];
  const spanCount = allEvents.filter((e) => e.kind === "span").length;
  const logCount = allEvents.filter((e) => e.kind === "log").length;

  return (
    <div className="space-y-4">
      {summary && <SummaryBar summary={summary} />}

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>

        <select
          value={opFilter}
          onChange={(e) => setOpFilter(e.target.value)}
          className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        >
          <option value="">All Operations</option>
          {Object.entries(OP_CONFIG).map(([k, v]) => (
            <option key={k} value={k}>{v.icon} {v.label}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Search events..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-[200px] rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        />

        <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none self-center">
          <input
            type="checkbox"
            checked={showLogs}
            onChange={(e) => setShowLogs(e.target.checked)}
            className="rounded border-zinc-600 bg-zinc-800 text-blue-500 focus:ring-0 focus:ring-offset-0 h-3 w-3"
          />
          Logs
        </label>

        <div className="text-xs text-zinc-500 self-center font-mono">
          {spanCount} span{spanCount !== 1 ? "s" : ""}
          {showLogs && logCount > 0 && ` + ${logCount} log${logCount !== 1 ? "s" : ""}`}
        </div>
      </div>

      {/* Unified event list */}
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 divide-y divide-zinc-800/50 max-h-[600px] overflow-auto">
        {isLoading ? (
          <div className="p-8 text-center text-zinc-500 text-sm">Loading events...</div>
        ) : allEvents.length === 0 ? (
          <div className="p-8 text-center text-zinc-500 text-sm">
            No events recorded yet. Events appear as agents execute operations.
          </div>
        ) : (
          allEvents.map((ev) =>
            ev.kind === "span" ? (
              <SpanRow
                key={(ev as TraceSpan).id}
                span={ev as TraceSpan}
                expanded={expandedId === (ev as TraceSpan).id}
                onToggle={() => setExpandedId(expandedId === (ev as TraceSpan).id ? null : (ev as TraceSpan).id)}
              />
            ) : (
              <LogRow key={(ev as LogEntry).id || (ev as LogEntry).timestamp} log={ev as LogEntry} />
            ),
          )
        )}
      </div>
    </div>
  );
}
