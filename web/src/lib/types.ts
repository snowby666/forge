export type AgentStatusValue = "done" | "in-progress" | "pending" | "failed" | "cancelled";

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
  started_at?: string;
  finished_at?: string;
  elapsed_s?: number;
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
  value: string;
  secret: boolean;
  description?: string;
}

export type ServiceCategory = "core" | "build" | "automation" | "ui" | "deploy";
export type ServiceType = "docker" | "host" | "external";

export interface ServiceHealth {
  name: string;
  status: "ok" | "error";
  latency_ms?: number;
  error?: string;
  description?: string;
  port?: number;
  type?: ServiceType;
  category?: ServiceCategory;
}

export interface ServiceHealthResponse {
  services: ServiceHealth[];
}

export interface DesignComponentVariant {
  name: string;
  description: string;
  tailwind_classes: string;
}

export interface DesignComponentState {
  state: string;
  description: string;
  tailwind_classes: string;
}

export interface DesignComponent {
  name: string;
  file_path?: string;
  description?: string;
  purpose?: string;
  shadcn_base?: string;
  is_demo_critical?: boolean;
  estimated_minutes?: number;
  variants?: DesignComponentVariant[];
  states?: DesignComponentState[];
  props_interface?: string;
}

export interface DesignScreen {
  route: string;
  name: string;
  purpose?: string;
  primary_action?: string;
  secondary_actions?: string[];
  information_hierarchy?: string[];
}

export interface DesignCritique {
  overall_score?: number;
  issues?: string[];
  strengths?: string[];
}

export interface StitchScreen {
  screen_name: string;
  image_url: string;
  project_id: string;
}

export interface DesignData {
  design_md: string;
  screenshots: string[];
  tokens: Record<string, unknown>;
  components: DesignComponent[];
  screens: DesignScreen[];
  personality?: string;
  critique?: DesignCritique;
  figma_file_id?: string;
  stitch_screens?: StitchScreen[];
}

export interface Artifact {
  key: string;
  data: unknown;
}

export interface BatchOperation {
  action: "delete" | "reroll";
  ids: string[];
}

export interface BatchResult {
  ok: boolean;
  results: Array<{ id: string; success: boolean; error?: string }>;
}

export interface WsAgentStatusMessage {
  type: "agent_status";
  hackathon_id: string;
  agent_id: string;
  status: AgentStatusValue;
}

export type WsMessage = WsAgentStatusMessage;

export interface HealthResponse {
  status: string;
  version?: string;
  uptime?: number;
}

// ── Tracing ─────────────────────────────────────────────────────────────────

export type TraceOp = "llm" | "mcp" | "http" | "file" | "redis" | "subprocess" | "artifact" | "log" | "daytona";

export interface TraceSpan {
  kind?: "span";
  id: string;
  hackathon_id: string;
  agent_id: string;
  op: TraceOp;
  name: string;
  status: "ok" | "error";
  started_at: string;
  finished_at: string;
  elapsed_s: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string | null;
  tags?: Record<string, unknown>;
}

export interface TraceSummary {
  total_spans: number;
  by_op: Record<string, number>;
  by_agent: Record<string, number>;
  total_llm_tokens: number;
  total_llm_cost_usd: number;
  total_file_writes: number;
  error_count: number;
}

export interface ArtifactEntry {
  name: string;
  type: string;
  agent_id: string;
  timestamp: string;
  summary: string;
  meta?: Record<string, unknown>;
}

export interface TraceListResponse {
  total: number;
  offset: number;
  limit: number;
  spans: TraceSpan[];
}
