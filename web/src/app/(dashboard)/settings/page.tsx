"use client"

import { useCallback, useState } from "react"
import useSWR from "swr"
import {
  Card,
  CardContent,
} from "@/components/ui/card"
import { ConfigEditor } from "@/components/config-editor"
import { SystemHealth } from "@/components/system-health"
import { fetchConfig, fetchServiceHealth, updateConfig } from "@/lib/api"
import type { ConfigEntry, ServiceHealth } from "@/lib/types"

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

      {healthLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-lg bg-muted/50"
            />
          ))}
        </div>
      ) : health && health.length > 0 ? (
        <SystemHealth services={health} />
      ) : (
        <p className="text-sm text-muted-foreground">
          No service health data available.
        </p>
      )}
    </div>
  )
}
