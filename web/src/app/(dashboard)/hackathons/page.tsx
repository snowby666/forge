"use client"

import { useCallback, useMemo, useState } from "react"
import Link from "next/link"
import useSWR from "swr"
import { LayoutGrid, List, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { HackathonTable } from "@/components/hackathon-table"
import { useHackathons } from "@/hooks/use-hackathons"
import {
  deleteHackathon,
  fetchCheckpoints,
  rerollHackathon,
} from "@/lib/api"
import type { AgentPhaseName, Checkpoint, Hackathon } from "@/lib/types"
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

const PHASE_PROGRESS: Record<AgentPhaseName, number> = {
  intelligence: 12,
  strategy: 25,
  design: 37,
  build: 50,
  verify: 62,
  polish: 75,
  submission: 87,
  infra: 100,
}

function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-400"
  if (score >= 60) return "text-yellow-400"
  if (score >= 40) return "text-orange-400"
  return "text-red-400"
}

function deadlineLabel(days: number) {
  if (days < 0) return "Expired"
  if (days === 0) return "Today"
  if (days === 1) return "Tomorrow"
  return `${days}d left`
}

function ProgressRing({
  progress,
  size = 36,
}: {
  progress: number
  size?: number
}) {
  const r = (size - 4) / 2
  const c = 2 * Math.PI * r
  const offset = c * (1 - progress / 100)

  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        className="text-muted/50"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeDasharray={c}
        strokeDashoffset={offset}
        strokeLinecap="round"
        className="text-emerald-500 transition-[stroke-dashoffset] duration-500"
      />
    </svg>
  )
}

function HackathonCard({ hackathon }: { hackathon: Hackathon }) {
  const h = hackathon
  const progress = PHASE_PROGRESS[h.phase] ?? 0
  const prizes = h.brief.prizes ?? []

  return (
    <Link href={`/hackathon/${h.id}`}>
      <Card className="group h-full transition-colors hover:bg-accent/30">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="truncate text-sm group-hover:underline">
              {h.brief.name}
            </CardTitle>
            <ProgressRing progress={progress} size={32} />
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "font-mono text-sm font-bold",
                scoreColor(h.brief.score),
              )}
            >
              {h.brief.score}
            </span>
            <Badge
              variant="outline"
              className={cn(
                "text-[10px] capitalize",
                PHASE_BADGE[h.phase],
              )}
            >
              {h.phase}
            </Badge>
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {prizes.length > 0
                ? prizes.length === 1
                  ? prizes[0]
                  : `${prizes.length} prizes`
                : "No prizes"}
            </span>
            <span
              className={cn(
                h.brief.days_until_deadline <= 1 && "text-red-400",
                h.brief.days_until_deadline <= 3 &&
                  h.brief.days_until_deadline > 1 &&
                  "text-yellow-400",
              )}
            >
              {deadlineLabel(h.brief.days_until_deadline)}
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

export default function HackathonsPage() {
  const { hackathons, isLoading, mutate } = useHackathons()
  const [pendingDelete, setPendingDelete] = useState<string[] | null>(null)
  const [view, setView] = useState<"grid" | "list">("list")

  const { data: checkpoints } = useSWR<Checkpoint[]>(
    "/api/checkpoints",
    fetchCheckpoints,
    { refreshInterval: 10_000 },
  )

  const pendingHackathonIds = useMemo(() => {
    const ids = new Set<string>()
    checkpoints?.forEach((cp) => {
      if (cp.pending) ids.add(cp.hackathon_id)
    })
    return ids
  }, [checkpoints])

  const handleDelete = useCallback((ids: string[]) => {
    setPendingDelete(ids)
  }, [])

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return
    await Promise.all(pendingDelete.map(deleteHackathon))
    setPendingDelete(null)
    mutate()
  }, [pendingDelete, mutate])

  const handleReroll = useCallback(
    async (id: string) => {
      await rerollHackathon(id)
      mutate()
    },
    [mutate],
  )

  const filtered = useMemo(() => {
    const active = hackathons.filter((h) => h.phase !== "submission")
    const pending = hackathons.filter((h) => pendingHackathonIds.has(h.id))
    const completed = hackathons.filter((h) => h.phase === "submission")
    return { all: hackathons, active, pending, completed }
  }, [hackathons, pendingHackathonIds])

  function renderContent(items: Hackathon[]) {
    if (items.length === 0) {
      return (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No hackathons match this filter.
          </CardContent>
        </Card>
      )
    }

    if (view === "grid") {
      return (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map((h) => (
            <HackathonCard key={h.id} hackathon={h} />
          ))}
        </div>
      )
    }

    return (
      <HackathonTable
        hackathons={items}
        onDelete={handleDelete}
        onReroll={handleReroll}
      />
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Hackathons</h1>
        {!isLoading && (
          <Badge variant="outline" className="tabular-nums">
            {hackathons.length}
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-border/50 p-0.5">
          <Button
            variant={view === "list" ? "secondary" : "ghost"}
            size="icon-xs"
            onClick={() => setView("list")}
          >
            <List className="size-3.5" />
          </Button>
          <Button
            variant={view === "grid" ? "secondary" : "ghost"}
            size="icon-xs"
            onClick={() => setView("grid")}
          >
            <LayoutGrid className="size-3.5" />
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-lg bg-muted/50"
            />
          ))}
        </div>
      ) : (
        <Tabs defaultValue="all">
          <TabsList>
            <TabsTrigger value="all">
              All
              <Badge
                variant="outline"
                className="ml-1.5 px-1.5 text-[10px] tabular-nums"
              >
                {filtered.all.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="active">
              Active
              <Badge
                variant="outline"
                className="ml-1.5 px-1.5 text-[10px] tabular-nums"
              >
                {filtered.active.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="pending">
              Pending
              {filtered.pending.length > 0 && (
                <Badge
                  variant="outline"
                  className="ml-1.5 border-yellow-500/30 px-1.5 text-[10px] tabular-nums text-yellow-500"
                >
                  {filtered.pending.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="completed">
              Completed
              <Badge
                variant="outline"
                className="ml-1.5 px-1.5 text-[10px] tabular-nums"
              >
                {filtered.completed.length}
              </Badge>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="all" className="mt-4">
            {renderContent(filtered.all)}
          </TabsContent>
          <TabsContent value="active" className="mt-4">
            {renderContent(filtered.active)}
          </TabsContent>
          <TabsContent value="pending" className="mt-4">
            {renderContent(filtered.pending)}
          </TabsContent>
          <TabsContent value="completed" className="mt-4">
            {renderContent(filtered.completed)}
          </TabsContent>
        </Tabs>
      )}

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setPendingDelete(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Delete hackathon
              {pendingDelete && pendingDelete.length > 1 ? "s" : ""}?
            </DialogTitle>
            <DialogDescription>
              This will permanently remove{" "}
              {pendingDelete?.length === 1
                ? "this hackathon"
                : `${pendingDelete?.length} hackathons`}{" "}
              and all associated data. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              <Trash2 className="mr-1.5 size-3.5" />
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
