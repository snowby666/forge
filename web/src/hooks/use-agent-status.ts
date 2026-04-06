"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { fetchAgentStatuses } from "@/lib/api";
import { useRealtimeStatus } from "@/lib/ws";
import type { AgentStatus, AgentPhaseName, LAYER_AGENTS } from "@/lib/types";
import { LAYER_AGENTS as LAYERS } from "@/lib/types";

const REFRESH_INTERVAL_MS = 15_000;

function phaseForAgent(
  agentId: string,
): AgentPhaseName | undefined {
  for (const [phase, agents] of Object.entries(LAYERS) as [
    AgentPhaseName,
    readonly string[],
  ][]) {
    if (agents.includes(agentId)) return phase;
  }
  return undefined;
}

export function useAgentStatus(hackathonId: string | undefined) {
  const { data: polled, error, isLoading, mutate } = useSWR<AgentStatus[]>(
    hackathonId ? `/api/hackathon/${hackathonId}/agents` : null,
    () => fetchAgentStatuses(hackathonId!),
    { refreshInterval: REFRESH_INTERVAL_MS },
  );

  const { statuses: wsStatuses, connected } = useRealtimeStatus();

  const agents = useMemo(() => {
    if (!polled) return [];

    const wsForHackathon =
      hackathonId ? (wsStatuses[hackathonId] ?? {}) : {};

    return polled.map<AgentStatus>((agent) => {
      const wsStatus = wsForHackathon[agent.agent_id];
      if (wsStatus && wsStatus !== agent.status) {
        return {
          ...agent,
          status: wsStatus,
          phase: agent.phase ?? phaseForAgent(agent.agent_id) ?? agent.phase,
        };
      }
      return agent;
    });
  }, [polled, wsStatuses, hackathonId]);

  return {
    agents,
    error,
    isLoading,
    connected,
    mutate,
  };
}
