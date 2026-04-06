import type {
  Hackathon,
  Checkpoint,
  AgentStatus,
  AnalyticsData,
  ConfigEntry,
  ServiceHealth,
  LogEntry,
  DesignArtifact,
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

export function approveCheckpoint(hackathonId: string, checkpoint: string) {
  return apiFetch<void>(`/api/approve/${hackathonId}/${checkpoint}`, {
    method: "POST",
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
  return apiFetch<DesignArtifact[]>(`/api/hackathon/${hackathonId}/design`);
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
  return apiFetch<ConfigEntry[]>("/api/config", {
    method: "PUT",
    body: JSON.stringify(entries),
  });
}

// ── Services ────────────────────────────────────────────────

export function fetchServiceHealth() {
  return apiFetch<ServiceHealth[]>("/api/services/health");
}

export function fetchHealth() {
  return apiFetch<HealthResponse>("/health");
}

// ── Batch ───────────────────────────────────────────────────

export function batchOperation(op: BatchOperation) {
  return apiFetch<BatchResult[]>("/api/hackathon/batch", {
    method: "POST",
    body: JSON.stringify(op),
  });
}

export { ApiError };
