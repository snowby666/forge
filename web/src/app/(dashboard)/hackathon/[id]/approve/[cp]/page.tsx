"use client"

import { use, useCallback, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import { ArrowLeft, CheckCircle2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { CheckpointCard } from "@/components/checkpoint-card"
import { approveCheckpoint, fetchCheckpoints } from "@/lib/api"
import type { Checkpoint } from "@/lib/types"

export default function ApprovePage({
  params,
}: {
  params: Promise<{ id: string; cp: string }>
}) {
  const { id, cp } = use(params)
  const router = useRouter()
  const [status, setStatus] = useState<"idle" | "approving" | "done" | "error">("idle")

  const { data: checkpoints } = useSWR<Checkpoint[]>(
    "/api/checkpoints",
    fetchCheckpoints,
  )

  const checkpoint = checkpoints?.find(
    (c) => c.hackathon_id === id && c.checkpoint === cp,
  )

  const concepts =
    checkpoint?.checkpoint === "concept_approval" &&
    checkpoint.data?.concepts
      ? (checkpoint.data.concepts as Array<{
          project_name: string
          tagline: string
          total_score: number
          rank: number
        }>)
      : undefined

  const handleApprove = useCallback(async () => {
    setStatus("approving")
    try {
      await approveCheckpoint(id, cp)
      setStatus("done")
      setTimeout(() => router.push(`/hackathon/${id}`), 1500)
    } catch {
      setStatus("error")
    }
  }, [id, cp, router])

  if (!checkpoint) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Link href={`/hackathon/${id}`}>
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <h1 className="text-xl font-bold">Approve Checkpoint</h1>
        </div>
        <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
      </div>
    )
  }

  if (!checkpoint.pending) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Link href={`/hackathon/${id}`}>
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <h1 className="text-xl font-bold">Checkpoint</h1>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-emerald-400">
              <CheckCircle2 className="size-5" />
              Already Approved
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">
              The{" "}
              <span className="font-medium text-foreground">
                {cp.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </span>{" "}
              checkpoint has already been approved.
            </p>
            {typeof checkpoint.data?.approved_at === "string" && (
              <Badge variant="secondary" className="text-xs">
                Approved {new Date(checkpoint.data.approved_at).toLocaleString()}
              </Badge>
            )}
            <div className="pt-2">
              <Link href={`/hackathon/${id}`}>
                <Button variant="outline" size="sm">
                  <ArrowLeft className="mr-1.5 size-3.5" />
                  Back to Hackathon
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (status === "done") {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24">
        <CheckCircle2 className="size-12 text-emerald-500" />
        <h2 className="text-lg font-semibold">Checkpoint Approved</h2>
        <p className="text-sm text-muted-foreground">
          Redirecting to hackathon detail…
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link href={`/hackathon/${id}`}>
          <Button variant="ghost" size="icon-sm">
            <ArrowLeft className="size-4" />
          </Button>
        </Link>
        <h1 className="text-xl font-bold">Approve Checkpoint</h1>
      </div>

      {status === "error" && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          Failed to approve checkpoint. Please try again.
        </div>
      )}

      <div className="mx-auto max-w-lg">
        <CheckpointCard
          checkpoint={checkpoint}
          hackathonId={id}
          concepts={concepts}
          onApprove={handleApprove}
        />
      </div>
    </div>
  )
}
