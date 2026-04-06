"use client"

import useSWR from "swr"
import { Activity, DollarSign, TrendingUp } from "lucide-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card"
import { CostChart } from "@/components/cost-chart"
import { fetchAnalytics } from "@/lib/api"
import type { AnalyticsData } from "@/lib/types"

export default function AnalyticsPage() {
  const { data, isLoading } = useSWR<AnalyticsData>(
    "/api/analytics",
    () => fetchAnalytics(),
    { refreshInterval: 30_000 },
  )

  const totalCost =
    data?.cost_by_hackathon?.reduce((sum, h) => sum + h.cost_usd, 0) ?? 0
  const totalRuns =
    data?.daily_runs?.reduce((sum, d) => sum + d.count, 0) ?? 0

  const summaryCards = [
    {
      title: "Total Cost",
      value: `$${totalCost.toFixed(2)}`,
      icon: DollarSign,
      color: "text-blue-400",
    },
    {
      title: "Total Runs",
      value: totalRuns.toLocaleString(),
      icon: Activity,
      color: "text-emerald-400",
    },
    {
      title: "Avg Success Rate",
      value: data?.success_rate != null ? `${data.success_rate.toFixed(1)}%` : "—",
      icon: TrendingUp,
      color: "text-violet-400",
    },
  ]

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
        <div className="grid gap-4 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <div className="h-4 w-24 animate-pulse rounded bg-muted" />
              </CardHeader>
              <CardContent>
                <div className="h-8 w-20 animate-pulse rounded bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-72 animate-pulse rounded-lg bg-muted/50"
            />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        {summaryCards.map((card) => (
          <Card key={card.title}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardDescription className="text-xs font-medium">
                {card.title}
              </CardDescription>
              <card.icon className={`size-4 ${card.color}`} />
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{card.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {data && <CostChart data={data} />}
    </div>
  )
}
