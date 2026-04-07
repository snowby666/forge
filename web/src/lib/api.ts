import type {
  Hackathon,
  Checkpoint,
  AgentStatus,
  AnalyticsData,
  ConfigEntry,
  ServiceHealth,
  ServiceHealthResponse,
  LogEntry,
  DesignData,
  Artifact,
  BatchOperation,
  BatchResult,
  HealthResponse,
} from "./types";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || res.statusText);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Hackathons ──────────────────────────────────────────────

export function fetchHackathons() {
  return apiFetch<Hackathon[]>("/api/hackathons");
}

export function deleteHackathon(id: string) {
  return apiFetch<void>(`/api/hackathon/${id}`, { method: "DELETE" });
}

export function rerollHackathon(id: string) {
  return apiFetch<Hackathon>(`/api/hackathon/${id}/reroll`, {
    method: "POST",
  });
}

// ── Checkpoints ─────────────────────────────────────────────

export function fetchCheckpoints() {
  return apiFetch<Checkpoint[]>("/api/checkpoints");
}

export function approveCheckpoint(hackathonId: string, checkpoint: string, data?: Record<string, unknown>) {
  return apiFetch<void>(`/api/approve/${hackathonId}/${checkpoint}`, {
    method: "POST",
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
}

// ── Agent statuses ──────────────────────────────────────────

export function fetchAgentStatuses(hackathonId: string) {
  return apiFetch<AgentStatus[]>(`/api/hackathon/${hackathonId}/agents`);
}

export function triggerAgent(hackathonId: string, agentId: string) {
  return apiFetch<void>(
    `/api/hackathon/${hackathonId}/agent/${agentId}/trigger`,
    { method: "POST" },
  );
}

export function restartAgent(hackathonId: string, agentId: string) {
  return apiFetch<void>(
    `/api/hackathon/${hackathonId}/agent/${agentId}/restart`,
    { method: "POST" },
  );
}

// ── Logs & artifacts ────────────────────────────────────────

export function fetchLogs(hackathonId: string) {
  return apiFetch<LogEntry[]>(`/api/hackathon/${hackathonId}/logs`);
}

export function fetchDesignArtifacts(hackathonId: string) {
  return apiFetch<DesignData>(`/api/hackathon/${hackathonId}/design`);
}

export function fetchArtifacts(hackathonId: string) {
  return apiFetch<Artifact[]>(`/api/hackathon/${hackathonId}/artifacts`);
}

// ── Analytics ───────────────────────────────────────────────

export function fetchAnalytics(hackathonId?: string) {
  const path = hackathonId
    ? `/api/analytics/${hackathonId}`
    : "/api/analytics";
  return apiFetch<AnalyticsData>(path);
}

// ── Config ──────────────────────────────────────────────────

export function fetchConfig() {
  return apiFetch<ConfigEntry[]>("/api/config");
}

export function updateConfig(entries: ConfigEntry[]) {
  return apiFetch<{ ok: boolean; updated: number }>("/api/config", {
    method: "PUT",
    body: JSON.stringify({ entries: entries.map((e) => ({ key: e.key, value: e.value })) }),
  });
}

// ── Services ────────────────────────────────────────────────

export async function fetchServiceHealth(): Promise<ServiceHealth[]> {
  const res = await apiFetch<ServiceHealthResponse>("/api/services/health");
  return res.services;
}

export function fetchHealth() {
  return apiFetch<HealthResponse>("/health");
}

// ── Batch ───────────────────────────────────────────────────

export function batchOperation(op: BatchOperation) {
  return apiFetch<BatchResult>("/api/hackathon/batch", {
    method: "POST",
    body: JSON.stringify(op),
  });
}

// ── Cost & Time ─────────────────────────────────────────

export function fetchCost(hackathonId: string) {
  return apiFetch<{
    total_usd: number;
    total_tokens: number;
    by_agent: Record<string, { cost_usd: number; input_tokens: number; output_tokens: number; tokens: number; calls: number }>;
  }>(`/api/hackathon/${hackathonId}/cost`);
}

export function fetchElapsed(hackathonId: string) {
  return apiFetch<{
    total_elapsed_s: number | null;
    started_at: string | null;
    latest_finish: string | null;
    agent_times: Array<{ agent_id: string; elapsed_s: number; status: string }>;
  }>(`/api/hackathon/${hackathonId}/elapsed`);
}

// ── CLI Actions ─────────────────────────────────────────────

export function runScout(dryRun = false) {
  return apiFetch<{ ok: boolean; pid: number; message: string }>("/api/scout", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
}

export function runHackathon(hackathonId: string, opts?: { from_phase?: string; restart?: boolean }) {
  return apiFetch<{ ok: boolean; pid: number }>(`/api/hackathon/${hackathonId}/run`, {
    method: "POST",
    body: JSON.stringify(opts ?? {}),
  });
}

export function runSystemTest() {
  return apiFetch<{ ok: boolean; stdout: string; stderr: string }>("/api/test", {
    method: "POST",
  });
}

// ── Tracing ─────────────────────────────────────────────────────────────────

export function fetchTraces(
  hackathonId: string,
  opts?: { agent?: string; op?: string; status?: string; limit?: number; offset?: number },
) {
  const params = new URLSearchParams();
  if (opts?.agent) params.set("agent", opts.agent);
  if (opts?.op) params.set("op", opts.op);
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return apiFetch<import("./types").TraceListResponse>(
    `/api/hackathon/${hackathonId}/traces${qs ? `?${qs}` : ""}`,
  );
}

export function fetchTraceSummary(hackathonId: string) {
  return apiFetch<import("./types").TraceSummary>(
    `/api/hackathon/${hackathonId}/traces/summary`,
  );
}

export function fetchArtifactRegistry(hackathonId: string) {
  return apiFetch<import("./types").ArtifactEntry[]>(
    `/api/hackathon/${hackathonId}/artifact-registry`,
  );
}

export function fetchEvents(
  hackathonId: string,
  opts?: { kind?: string; agent?: string; limit?: number; offset?: number },
) {
  const params = new URLSearchParams();
  if (opts?.kind) params.set("kind", opts.kind);
  if (opts?.agent) params.set("agent", opts.agent);
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return apiFetch<{ total: number; offset: number; limit: number; events: import("./types").UnifiedEvent[] }>(
    `/api/hackathon/${hackathonId}/events${qs ? `?${qs}` : ""}`,
  );
}

export { ApiError };
