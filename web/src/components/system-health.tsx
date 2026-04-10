"use client"

import {
  Activity,
  Box,
  CheckCircle2,
  Cloud,
  Container,
  Database,
  Globe,
  MonitorSmartphone,
  Search,
  Server,
  Timer,
  Workflow,
  XCircle,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { ServiceCategory, ServiceHealth } from "@/lib/types"

const SERVICE_ICONS: Record<string, typeof Database> = {
  redis: Database,
  postgresql: Database,
  qdrant: Database,
  searxng: Search,
  temporal: Workflow,
  "temporal-ui": MonitorSmartphone,
  n8n: Workflow,
  daytona: Box,
  browser: Globe,
  "forge-api": Server,
  "forge-web": Cloud,
}

const CATEGORY_LABELS: Record<ServiceCategory, string> = {
  core: "Core Infrastructure",
  build: "Build & Sandbox",
  automation: "Automation",
  ui: "Dashboard & UI",
}

const CATEGORY_ORDER: ServiceCategory[] = ["core", "build", "automation", "ui"]

function latencyColor(ms: number) {
  if (ms < 20) return "text-emerald-400"
  if (ms < 100) return "text-yellow-400"
  if (ms < 500) return "text-orange-400"
  return "text-red-400"
}

function ServiceCard({ service }: { service: ServiceHealth }) {
  const Icon = SERVICE_ICONS[service.name] || Container
  const isOk = service.status === "ok"

  return (
    <Card
      className={`relative overflow-hidden transition-all duration-200 ${
        isOk
          ? "border-border/50 hover:border-emerald-500/30"
          : "border-red-500/30 bg-red-500/5 hover:border-red-500/50"
      }`}
    >
      <div
        className={`absolute inset-x-0 top-0 h-0.5 ${
          isOk ? "bg-emerald-500" : "bg-red-500"
        }`}
      />
      <CardHeader className="flex flex-row items-center gap-3 pb-2 pt-4">
        <div
          className={`rounded-lg p-2 ${
            isOk ? "bg-emerald-500/10" : "bg-red-500/10"
          }`}
        >
          <Icon
            className={`size-4 ${isOk ? "text-emerald-500" : "text-red-500"}`}
          />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="truncate text-sm capitalize">
            {service.name}
          </CardTitle>
          {service.port && (
            <p className="font-mono text-[10px] text-muted-foreground">
              :{service.port}
            </p>
          )}
        </div>
        {isOk ? (
          <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />
        ) : (
          <XCircle className="size-4 shrink-0 text-red-500" />
        )}
      </CardHeader>
      <CardContent className="pb-3 pt-0">
        {service.description && (
          <p className="mb-1.5 text-[11px] leading-tight text-muted-foreground">
            {service.description}
          </p>
        )}
        <div className="flex items-center gap-2">
          {service.latency_ms != null && (
            <div className="flex items-center gap-1">
              <Timer className="size-3 text-muted-foreground" />
              <span
                className={`font-mono text-xs font-medium ${latencyColor(service.latency_ms)}`}
              >
                {service.latency_ms}ms
              </span>
            </div>
          )}
          {service.type && (
            <Badge
              variant="outline"
              className="h-4 px-1 text-[9px] font-normal text-muted-foreground"
            >
              {service.type === "docker" ? "container" : "host"}
            </Badge>
          )}
        </div>
        {service.error && (
          <p className="mt-1.5 truncate text-[11px] text-red-400">
            {service.error}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function SystemHealth({ services }: { services: ServiceHealth[] }) {
  const totalOk = services.filter((s) => s.status === "ok").length
  const totalServices = services.length
  const allOk = totalOk === totalServices

  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat],
    services: services.filter((s) => (s.category ?? "core") === cat),
  })).filter((g) => g.services.length > 0)

  return (
    <section>
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          System Health
        </h2>
        <Badge
          variant="outline"
          className={
            allOk
              ? "border-emerald-500/30 text-emerald-400"
              : "border-red-500/30 text-red-400"
          }
        >
          <Activity className="mr-1 size-3" />
          {totalOk}/{totalServices} online
        </Badge>
      </div>

      <div className="space-y-4">
        {grouped.map((group) => (
          <div key={group.category}>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-muted-foreground/60">
              {group.label}
            </p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {group.services.map((s) => (
                <ServiceCard key={s.name} service={s} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
