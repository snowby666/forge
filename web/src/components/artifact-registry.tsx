"use client";

import useSWR from "swr";
import { fetchArtifactRegistry } from "@/lib/api";
import type { ArtifactEntry } from "@/lib/types";

const TYPE_COLORS: Record<string, string> = {
  markdown: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  typescript: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
  json: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  python: "bg-green-500/20 text-green-400 border-green-500/30",
  yaml: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  pdf: "bg-red-500/20 text-red-400 border-red-500/30",
  audio: "bg-pink-500/20 text-pink-400 border-pink-500/30",
  video: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  svg: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  report: "bg-violet-500/20 text-violet-400 border-violet-500/30",
};

const AGENT_PHASE: Record<string, string> = {
  hackathon_scout: "Intelligence",
  competitor_analyst: "Intelligence",
  judge_profiler: "Intelligence",
  sponsor_researcher: "Intelligence",
  strategy_director: "Strategy",
  pm: "Strategy",
  tech_architect: "Strategy",
  ui_ux_designer: "Design",
  frontend_engineer: "Build",
  backend_engineer: "Build",
  integration_engineer: "Build",
  test_engineer: "Build",
  devops: "Build",
  security: "Build",
  code_reviewer: "Verify",
  ux_auditor: "Verify",
  performance: "Verify",
  polish: "Polish",
  copy_writer: "Polish",
  data_seeder: "Polish",
  brand: "Polish",
  demo_producer: "Submission",
  pitch_writer: "Submission",
  submission: "Submission",
};

function groupByPhase(artifacts: ArtifactEntry[]): Map<string, ArtifactEntry[]> {
  const groups = new Map<string, ArtifactEntry[]>();
  for (const a of artifacts) {
    const phase = AGENT_PHASE[a.agent_id] || "Other";
    if (!groups.has(phase)) groups.set(phase, []);
    groups.get(phase)!.push(a);
  }
  return groups;
}

export default function ArtifactRegistry({ hackathonId }: { hackathonId: string }) {
  const { data: artifacts, isLoading } = useSWR(
    `/api/hackathon/${hackathonId}/artifact-registry`,
    () => fetchArtifactRegistry(hackathonId),
    { refreshInterval: 15_000 },
  );

  if (isLoading) {
    return <div className="p-8 text-center text-zinc-500 text-sm">Loading artifacts...</div>;
  }

  if (!artifacts || artifacts.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-500 text-sm">
        No artifacts registered yet. Artifacts appear as agents produce outputs.
      </div>
    );
  }

  const grouped = groupByPhase(artifacts);
  const phaseOrder = ["Intelligence", "Strategy", "Design", "Build", "Verify", "Polish", "Submission", "Other"];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-zinc-400">
        <span className="font-mono">{artifacts.length}</span> artifact{artifacts.length !== 1 ? "s" : ""} registered
      </div>

      {phaseOrder.map((phase) => {
        const items = grouped.get(phase);
        if (!items || items.length === 0) return null;
        return (
          <div key={phase}>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">{phase}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
              {items.map((a, i) => {
                const typeColor = TYPE_COLORS[a.type] || "bg-zinc-500/20 text-zinc-400 border-zinc-500/30";
                return (
                  <div
                    key={`${a.name}-${i}`}
                    className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono text-sm text-zinc-200 break-all">{a.name}</span>
                      <span className={`shrink-0 inline-flex rounded px-1.5 py-0.5 text-[10px] font-mono border ${typeColor}`}>
                        {a.type}
                      </span>
                    </div>
                    <div className="text-xs text-zinc-500">{a.summary}</div>
                    <div className="flex items-center gap-2 text-[10px] text-zinc-600">
                      <span className="font-mono bg-zinc-800 rounded px-1.5 py-0.5">{a.agent_id}</span>
                      {a.timestamp && (
                        <span>{new Date(a.timestamp).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
