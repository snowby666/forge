"use client"

import { useMemo } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from "recharts"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { AnalyticsData } from "@/lib/types"

const costConfig = {
  cost_usd: { label: "Cost (USD)", color: "hsl(217 91% 60%)" },
} satisfies ChartConfig

const timingConfig = {
  avg_seconds: { label: "Avg Time (s)", color: "hsl(280 84% 65%)" },
} satisfies ChartConfig

const successConfig = {
  success_pct: { label: "Success %", color: "hsl(142 71% 45%)" },
} satisfies ChartConfig

const dailyConfig = {
  count: { label: "Runs", color: "hsl(199 89% 48%)" },
} satisfies ChartConfig

interface CostChartProps {
  data: AnalyticsData
}

export function CostChart({ data }: CostChartProps) {
  const topSlowest = useMemo(
    () =>
      [...(data.agent_timing ?? [])]
        .sort((a, b) => b.avg_seconds - a.avg_seconds)
        .slice(0, 10),
    [data.agent_timing],
  )

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            Cost per Hackathon
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={costConfig} className="h-[220px] w-full">
            <BarChart data={data.cost_by_hackathon ?? []}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="name"
                tickLine={false}
                axisLine={false}
                fontSize={11}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                fontSize={11}
                tickFormatter={(v) => `$${v}`}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar
                dataKey="cost_usd"
                fill="var(--color-cost_usd)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            Slowest Agents (avg seconds)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={timingConfig} className="h-[220px] w-full">
            <BarChart data={topSlowest} layout="vertical">
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis
                type="number"
                tickLine={false}
                axisLine={false}
                fontSize={11}
              />
              <YAxis
                type="category"
                dataKey="agent_id"
                tickLine={false}
                axisLine={false}
                fontSize={10}
                width={100}
                tickFormatter={(v: string) => v.replace(/_/g, " ")}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar
                dataKey="avg_seconds"
                fill="var(--color-avg_seconds)"
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            Success Rates by Agent
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={successConfig} className="h-[220px] w-full">
            <BarChart data={data.success_rates ?? []}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="agent_id"
                tickLine={false}
                axisLine={false}
                fontSize={10}
                tickFormatter={(v: string) => v.replace(/_/g, " ")}
                angle={-45}
                textAnchor="end"
                height={60}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                fontSize={11}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar
                dataKey="success_pct"
                fill="var(--color-success_pct)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Daily Runs</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartContainer config={dailyConfig} className="h-[220px] w-full">
            <AreaChart data={data.daily_runs ?? []}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                fontSize={11}
              />
              <YAxis tickLine={false} axisLine={false} fontSize={11} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Area
                type="monotone"
                dataKey="count"
                fill="var(--color-count)"
                fillOpacity={0.2}
                stroke="var(--color-count)"
                strokeWidth={2}
              />
            </AreaChart>
          </ChartContainer>
        </CardContent>
      </Card>
    </div>
  )
}
