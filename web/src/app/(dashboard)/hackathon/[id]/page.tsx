"use client"

import { use, useCallback, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Palette,
  RefreshCw,
  ScrollText,
  Trash2,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { AgentTimeline } from "@/components/agent-timeline"
import { CheckpointCard } from "@/components/checkpoint-card"
import { useAgentStatus } from "@/hooks/use-agent-status"
import {
  approveCheckpoint,
  deleteHackathon,
  fetchArtifacts,
  fetchCheckpoints,
  fetchHackathons,
  rerollHackathon,
  restartAgent,
  triggerAgent,
} from "@/lib/api"
import type { Artifact, Checkpoint, Hackathon } from "@/lib/types"

const PHASE_BADGE: Record<string, string> = {
  intelligence: "border-blue-500/20 bg-blue-500/10 text-blue-400",
  strategy: "border-violet-500/20 bg-violet-500/10 text-violet-400",
  design: "border-pink-500/20 bg-pink-500/10 text-pink-400",
  build: "border-amber-500/20 bg-amber-500/10 text-amber-400",
  verify: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
  polish: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",
  submission: "border-orange-500/20 bg-orange-500/10 text-orange-400",
  infra: "border-zinc-500/20 bg-zinc-500/10 text-zinc-400",
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
  return `${days} days left`
}

export default function HackathonDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [expandedArtifact, setExpandedArtifact] = useState<string | null>(null)

  const { data: hackathons } = useSWR<Hackathon[]>(
    "/api/hackathons",
    fetchHackathons,
    { refreshInterval: 15_000 },
  )
  const hackathon = hackathons?.find((h) => h.id === id)

  const { agents, connected } = useAgentStatus(id)

  const { data: checkpoints, mutate: mutateCheckpoints } = useSWR<Checkpoint[]>(
    "/api/checkpoints",
    fetchCheckpoints,
    { refreshInterval: 10_000 },
  )
  const hackCheckpoints = checkpoints?.filter((c) => c.hackathon_id === id) ?? []

  const { data: artifacts } = useSWR<Artifact[]>(
    `/api/hackathon/${id}/artifacts`,
    () => fetchArtifacts(id),
    { refreshInterval: 30_000 },
  )

  const handleTrigger = useCallback(
    async (agentId: string) => {
      await triggerAgent(id, agentId)
    },
    [id],
  )

  const handleRestart = useCallback(
    async (agentId: string) => {
      await restartAgent(id, agentId)
    },
    [id],
  )

  const handleReroll = useCallback(async () => {
    await rerollHackathon(id)
  }, [id])

  const handleDeleteConfirm = useCallback(async () => {
    await deleteHackathon(id)
    router.push("/hackathons")
  }, [id, router])

  const handleApprove = useCallback(
    async (cp: Checkpoint) => {
      await approveCheckpoint(id, cp.checkpoint)
      mutateCheckpoints()
    },
    [id, mutateCheckpoints],
  )

  if (!hackathon) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-muted" />
        <div className="h-64 animate-pulse rounded-lg bg-muted/50" />
      </div>
    )
  }

  const { brief } = hackathon

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Link href="/hackathons">
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold">{brief.name}</h1>
              <span className={`font-mono text-lg font-bold ${scoreColor(brief.score)}`}>
                {brief.score}/100
              </span>
              <Badge
                variant="outline"
                className={`text-[10px] capitalize ${PHASE_BADGE[hackathon.phase] ?? ""}`}
              >
                {hackathon.phase}
              </Badge>
              {connected && (
                <span className="inline-block size-2 rounded-full bg-emerald-500" title="WebSocket connected" />
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              {deadlineLabel(brief.days_until_deadline)}
              {brief.url && (
                <>
                  {" · "}
                  <a
                    href={brief.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 hover:underline"
                  >
                    Hackathon Page
                    <ExternalLink className="size-3" />
                  </a>
                </>
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link href={`/hackathon/${id}/logs`}>
            <Button variant="outline" size="sm">
              <ScrollText className="mr-1.5 size-3.5" />
              Logs
            </Button>
          </Link>
          <Link href={`/hackathon/${id}/design`}>
            <Button variant="outline" size="sm">
              <Palette className="mr-1.5 size-3.5" />
              Design
            </Button>
          </Link>
          <Separator orientation="vertical" className="!h-6" />
          <Button variant="outline" size="sm" onClick={handleReroll}>
            <RefreshCw className="mr-1.5 size-3.5" />
            Reroll
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="mr-1.5 size-3.5" />
            Delete
          </Button>
        </div>
      </div>

      <Tabs defaultValue="pipeline">
        <TabsList>
          <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
          <TabsTrigger value="checkpoints">
            Checkpoints
            {hackCheckpoints.filter((c) => c.pending).length > 0 && (
              <Badge variant="secondary" className="ml-1.5 size-5 justify-center rounded-full p-0 text-[10px]">
                {hackCheckpoints.filter((c) => c.pending).length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
        </TabsList>

        <TabsContent value="pipeline" className="mt-4">
          {agents.length > 0 ? (
            <AgentTimeline
              agents={agents}
              hackathonId={id}
              onTrigger={handleTrigger}
              onRestart={handleRestart}
            />
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No agent data available yet.
            </p>
          )}
        </TabsContent>

        <TabsContent value="checkpoints" className="mt-4">
          {hackCheckpoints.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {hackCheckpoints.map((cp) => (
                <CheckpointCard
                  key={cp.checkpoint}
                  checkpoint={cp}
                  hackathonId={id}
                  onApprove={() => handleApprove(cp)}
                />
              ))}
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No checkpoints recorded yet.
            </p>
          )}
        </TabsContent>

        <TabsContent value="artifacts" className="mt-4">
          {artifacts && artifacts.length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {artifacts.map((a) => (
                <Card key={a.id}>
                  <CardHeader className="flex flex-row items-center justify-between pb-2">
                    <CardTitle className="truncate text-sm">
                      <FileText className="mr-1.5 inline size-3.5" />
                      {a.name}
                    </CardTitle>
                    <Badge variant="outline" className="text-[10px]">
                      {a.type}
                    </Badge>
                  </CardHeader>
                  <CardContent>
                    <button
                      className="w-full text-left"
                      onClick={() =>
                        setExpandedArtifact(expandedArtifact === a.id ? null : a.id)
                      }
                    >
                      {expandedArtifact === a.id ? (
                        <pre className="max-h-64 overflow-auto rounded bg-zinc-950 p-3 font-mono text-xs text-zinc-300">
                          {JSON.stringify(a, null, 2)}
                        </pre>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          {a.path ?? a.url ?? "Click to expand"}
                          {a.size != null && ` · ${(a.size / 1024).toFixed(1)}KB`}
                        </p>
                      )}
                    </button>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No artifacts available yet.
            </p>
          )}
        </TabsContent>
      </Tabs>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete &ldquo;{brief.name}&rdquo;?</DialogTitle>
            <DialogDescription>
              This will permanently remove this hackathon and all associated
              agents, checkpoints, and artifacts.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteConfirm}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
