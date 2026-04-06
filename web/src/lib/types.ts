export type AgentStatusValue = "done" | "in-progress" | "pending" | "failed";

export type CheckpointName =
  | "concept_approval"
  | "design_approval"
  | "quality_review"
  | "submission_approval";

export type AgentPhaseName =
  | "intelligence"
  | "strategy"
  | "design"
  | "build"
  | "verify"
  | "polish"
  | "submission"
  | "infra";

export const LAYER_AGENTS: Record<AgentPhaseName, readonly string[]> = {
  intelligence: [
    "hackathon_scout",
    "competitor_analyst",
    "judge_profiler",
    "sponsor_researcher",
  ],
  strategy: ["strategy_director", "pm", "tech_architect"],
  design: ["ui_ux_designer"],
  build: [
    "frontend_engineer",
    "backend_engineer",
    "integration_engineer",
    "test_engineer",
    "devops",
    "security",
  ],
  verify: ["code_reviewer", "ux_auditor", "performance"],
  polish: ["polish", "copy_writer", "data_seeder", "brand"],
  submission: ["demo_producer", "pitch_writer", "submission"],
  infra: [
    "memory_keeper",
    "monitor",
    "calendar",
    "knowledge_updater",
    "outcome_tracker",
  ],
} as const;

export const ALL_AGENT_IDS = Object.values(LAYER_AGENTS).flat();

export interface HackathonBrief {
  name: string;
  score: number;
  url: string;
  theme: string;
  prizes: string[];
  days_until_deadline: number;
  [key: string]: unknown;
}

export interface Hackathon {
  id: string;
  brief: HackathonBrief;
  phase: AgentPhaseName;
}

export interface Checkpoint {
  hackathon_id: string;
  checkpoint: CheckpointName;
  pending: boolean;
  data: Record<string, unknown>;
}

export interface AgentStatus {
  agent_id: string;
  status: AgentStatusValue;
  phase: AgentPhaseName;
  updated_at?: string;
  error?: string;
}

export interface AgentPhase {
  name: AgentPhaseName;
  agents: AgentStatus[];
}

export interface AnalyticsData {
  hackathon_id?: string;
  total_hackathons?: number;
  active_agents?: number;
  success_rate?: number;
  avg_completion_time?: number;
  cost_by_hackathon?: Array<{ name: string; cost_usd: number }>;
  agent_timing?: Array<{ agent_id: string; avg_seconds: number }>;
  success_rates?: Array<{
    agent_id: string;
    success_pct: number;
    total_runs: number;
  }>;
  daily_runs?: Array<{ date: string; count: number }>;
  [key: string]: unknown;
}

export interface ConfigEntry {
  key: string;
  value: unknown;
  type: string;
  secret?: boolean;
  description?: string;
}

export interface ServiceHealth {
  service: string;
  status: "healthy" | "degraded" | "down";
  latency_ms?: number;
  last_check?: string;
  details?: Record<string, unknown>;
}

export interface LogEntry {
  timestamp: string;
  level: "debug" | "info" | "warning" | "error" | "critical";
  agent_id?: string;
  message: string;
  data?: Record<string, unknown>;
}

export interface DesignArtifact {
  id: string;
  hackathon_id: string;
  type: string;
  name: string;
  url?: string;
  content?: string;
  created_at: string;
}

export interface Artifact {
  id: string;
  hackathon_id: string;
  type: string;
  name: string;
  path?: string;
  url?: string;
  size?: number;
  created_at: string;
}

export interface BatchOperation {
  action: string;
  hackathon_ids: string[];
  params?: Record<string, unknown>;
}

export interface BatchResult {
  hackathon_id: string;
  success: boolean;
  error?: string;
}

export interface WsAgentStatusMessage {
  type: "agent_status";
  hackathon_id: string;
  agent_id: string;
  status: AgentStatusValue;
}

export interface WsLogMessage {
  type: "log";
  hackathon_id: string;
  agent_id: string;
  message: string;
  level: LogEntry["level"];
  timestamp: string;
}

export type WsMessage = WsAgentStatusMessage | WsLogMessage;

export interface HealthResponse {
  status: string;
  version?: string;
  uptime?: number;
}
