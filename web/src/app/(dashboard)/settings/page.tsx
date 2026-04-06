"use client"

import { useCallback, useState } from "react"
import useSWR from "swr"
import { CheckCircle2, XCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ConfigEditor } from "@/components/config-editor"
import { fetchConfig, fetchServiceHealth, updateConfig } from "@/lib/api"
import type { ConfigEntry, ServiceHealth } from "@/lib/types"

function statusColor(status: ServiceHealth["status"]) {
  switch (status) {
    case "healthy":
      return "border-emerald-500/30 bg-emerald-500/5"
    case "degraded":
      return "border-yellow-500/30 bg-yellow-500/5"
    case "down":
      return "border-red-500/30 bg-red-500/5"
  }
}

function StatusIcon({ status }: { status: ServiceHealth["status"] }) {
  if (status === "healthy")
    return <CheckCircle2 className="size-4 text-emerald-500" />
  return <XCircle className="size-4 text-red-500" />
}

export default function SettingsPage() {
  const [toast, setToast] = useState<{
    type: "success" | "error"
    message: string
  } | null>(null)

  const {
    data: config,
    isLoading: configLoading,
    mutate: mutateConfig,
  } = useSWR<ConfigEntry[]>("/api/config", fetchConfig)

  const { data: health, isLoading: healthLoading } = useSWR<ServiceHealth[]>(
    "/api/services/health",
    fetchServiceHealth,
    { refreshInterval: 30_000 },
  )

  const handleSave = useCallback(
    async (entries: ConfigEntry[]) => {
      try {
        await updateConfig(entries)
        mutateConfig()
        setToast({ type: "success", message: "Configuration saved." })
        setTimeout(() => setToast(null), 3000)
      } catch {
        setToast({ type: "error", message: "Failed to save configuration." })
        setTimeout(() => setToast(null), 4000)
      }
    },
    [mutateConfig],
  )

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      {toast && (
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            toast.type === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "border-red-500/30 bg-red-500/10 text-red-400"
          }`}
        >
          {toast.message}
        </div>
      )}

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Configuration</h2>
        {configLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-10 animate-pulse rounded bg-muted/50"
              />
            ))}
          </div>
        ) : config ? (
          <Card>
            <CardContent className="pt-6">
              <ConfigEditor entries={config} onSave={handleSave} />
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-muted-foreground">
            No configuration entries found.
          </p>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Service Health</h2>
        {healthLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-lg bg-muted/50"
              />
            ))}
          </div>
        ) : health && health.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {health.map((s) => (
              <Card key={s.service} className={statusColor(s.status)}>
                <CardHeader className="flex flex-row items-center justify-between pb-2">
                  <CardTitle className="text-sm capitalize">
                    {s.service}
                  </CardTitle>
                  <StatusIcon status={s.status} />
                </CardHeader>
                <CardContent>
                  <Badge
                    variant="outline"
                    className="capitalize"
                  >
                    {s.status}
                  </Badge>
                  {s.latency_ms != null && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {s.latency_ms}ms latency
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No service health data available.
          </p>
        )}
      </section>
    </div>
  )
}
