"use client"

import { use, useCallback, useState } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { LogViewer } from "@/components/log-viewer"
import { fetchLogs } from "@/lib/api"
import { useRealtimeStatus } from "@/lib/ws"
import type { LogEntry, WsLogMessage } from "@/lib/types"

export default function LogsPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const [wsLogs, setWsLogs] = useState<LogEntry[]>([])

  const { data: polledLogs, isLoading } = useSWR<LogEntry[]>(
    `/api/hackathon/${id}/logs`,
    () => fetchLogs(id),
    { refreshInterval: 5_000 },
  )

  const handleWsLog = useCallback(
    (msg: WsLogMessage) => {
      if (msg.hackathon_id !== id) return
      setWsLogs((prev) => [
        ...prev,
        {
          timestamp: msg.timestamp,
          level: msg.level,
          agent_id: msg.agent_id,
          message: msg.message,
        },
      ])
    },
    [id],
  )

  useRealtimeStatus({ onLog: handleWsLog })

  const allLogs: LogEntry[] = [
    ...(polledLogs ?? []),
    ...wsLogs.filter(
      (wl) =>
        !(polledLogs ?? []).some(
          (pl) =>
            pl.timestamp === wl.timestamp && pl.message === wl.message,
        ),
    ),
  ].sort(
    (a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  )

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col space-y-4">
      <div className="flex items-center gap-3">
        <Link href={`/hackathon/${id}`}>
          <Button variant="ghost" size="icon-sm">
            <ArrowLeft className="size-4" />
          </Button>
        </Link>
        <h1 className="text-xl font-bold">Live Logs</h1>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border">
        <LogViewer logs={allLogs} loading={isLoading} />
      </div>
    </div>
  )
}
