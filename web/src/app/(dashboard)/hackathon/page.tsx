"use client"

import { useMemo } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowRight, Terminal } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { LogViewer } from "@/components/log-viewer"
import { useHackathons } from "@/hooks/use-hackathons"
import { fetchLogs } from "@/lib/api"
import type { AgentPhaseName, LogEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

const PHASE_BADGE: Record<AgentPhaseName, string> = {
  intelligence: "border-blue-500/20 bg-blue-500/10 text-blue-400",
  strategy: "border-violet-500/20 bg-violet-500/10 text-violet-400",
  design: "border-pink-500/20 bg-pink-500/10 text-pink-400",
  build: "border-amber-500/20 bg-amber-500/10 text-amber-400",
  verify: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
  polish: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",
  submission: "border-orange-500/20 bg-orange-500/10 text-orange-400",
  infra: "border-zinc-500/20 bg-zinc-500/10 text-zinc-400",
}

export default function LiveLogsHubPage() {
  const { hackathons, isLoading } = useHackathons()

  const activeHackathon = useMemo(
    () => hackathons.find((h) => h.phase !== "submission") ?? hackathons[0],
    [hackathons],
  )

  const { data: recentLogs, isLoading: logsLoading } = useSWR<LogEntry[]>(
    activeHackathon ? `/api/hackathon/${activeHackathon.id}/logs` : null,
    () => (activeHackathon ? fetchLogs(activeHackathon.id) : Promise.resolve([])),
    { refreshInterval: 5_000 },
  )

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col space-y-6">
      <div className="flex items-center gap-3">
        <Terminal className="size-5 text-muted-foreground" />
        <h1 className="text-2xl font-bold tracking-tight">Live Logs</h1>
        {!isLoading && (
          <Badge variant="outline" className="tabular-nums">
            {hackathons.length} hackathon{hackathons.length !== 1 ? "s" : ""}
          </Badge>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded-lg bg-muted/50"
            />
          ))}
        </div>
      ) : hackathons.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No hackathons found. Run <code>forge scout</code> to discover hackathons.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hackathons.map((h) => (
              <Card key={h.id} className="group transition-colors hover:bg-accent/30">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="truncate text-sm">
                      {h.brief.name}
                    </CardTitle>
                    <Badge
                      variant="outline"
                      className={cn(
                        "shrink-0 text-[10px] capitalize",
                        PHASE_BADGE[h.phase],
                      )}
                    >
                      {h.phase}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <Link href={`/hackathon/${h.id}/logs`}>
                    <Button variant="outline" size="sm" className="w-full">
                      View Logs
                      <ArrowRight className="ml-1.5 size-3" />
                    </Button>
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>

          {activeHackathon && (
            <div className="flex min-h-0 flex-1 flex-col space-y-2">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium text-muted-foreground">
                  Recent logs &mdash; {activeHackathon.brief.name}
                </h2>
                <Link href={`/hackathon/${activeHackathon.id}/logs`}>
                  <Button variant="ghost" size="sm">
                    Full view
                    <ArrowRight className="ml-1 size-3" />
                  </Button>
                </Link>
              </div>
              <div className="min-h-0 flex-1 overflow-hidden rounded-lg border">
                <LogViewer
                  logs={recentLogs ?? []}
                  loading={logsLoading}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
