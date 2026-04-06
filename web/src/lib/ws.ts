"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type {
  AgentStatusValue,
  WsMessage,
  WsLogMessage,
} from "./types";

export type AgentStatusMap = Record<
  string, // hackathon_id
  Record<string, AgentStatusValue> // agent_id → status
>;

interface UseRealtimeStatusOptions {
  onLog?: (msg: WsLogMessage) => void;
  enabled?: boolean;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

function wsUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/ws`;
}

export function useRealtimeStatus(opts: UseRealtimeStatusOptions = {}) {
  const { onLog, enabled = true } = opts;
  const [statuses, setStatuses] = useState<AgentStatusMap>({});
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const onLogRef = useRef(onLog);
  onLogRef.current = onLog;

  const connect = useCallback(() => {
    if (!enabled || typeof window === "undefined") return;

    const url = wsUrl();
    if (!url) return;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      retriesRef.current = 0;
    };

    ws.onmessage = (ev) => {
      let msg: WsMessage;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }

      if (msg.type === "agent_status") {
        setStatuses((prev) => {
          const hackathon = prev[msg.hackathon_id] ?? {};
          if (hackathon[msg.agent_id] === msg.status) return prev;
          return {
            ...prev,
            [msg.hackathon_id]: {
              ...hackathon,
              [msg.agent_id]: msg.status,
            },
          };
        });
      } else if (msg.type === "log") {
        onLogRef.current?.(msg);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [enabled]);

  const scheduleReconnect = useCallback(() => {
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** retriesRef.current,
      RECONNECT_MAX_MS,
    );
    retriesRef.current += 1;
    timerRef.current = setTimeout(connect, delay);
  }, [connect]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(timerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  return { statuses, connected } as const;
}
