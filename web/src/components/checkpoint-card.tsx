"use client"

import { useState } from "react"
import { CheckCircle2, Clock, ThumbsDown, ThumbsUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { Checkpoint } from "@/lib/types"
import { cn } from "@/lib/utils"

interface ConceptOption {
  project_name: string
  tagline: string
  total_score: number
  rank: number
}

interface CheckpointCardProps {
  checkpoint: Checkpoint
  hackathonId: string
  concepts?: ConceptOption[]
  onApprove: (data?: Record<string, unknown>) => void
}

function prettifyCheckpoint(name: string) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

export function CheckpointCard({
  checkpoint,
  concepts,
  onApprove,
}: CheckpointCardProps) {
  const [selected, setSelected] = useState<number | null>(null)
  const isConcept = checkpoint.checkpoint === "concept_approval"

  return (
    <Card
      className={cn(
        "transition-all",
        checkpoint.pending &&
          "border-yellow-500/50 shadow-md shadow-yellow-500/10",
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-sm font-medium">
          {prettifyCheckpoint(checkpoint.checkpoint)}
        </CardTitle>
        {checkpoint.pending ? (
          <Badge
            variant="outline"
            className="animate-pulse gap-1 border-yellow-500/50 text-yellow-500"
          >
            <Clock className="size-3" />
            Pending
          </Badge>
        ) : (
          <Badge variant="secondary" className="gap-1 text-emerald-500">
            <CheckCircle2 className="size-3" />
            Approved
            {typeof checkpoint.data?.approved_at === "string" && (
              <span className="ml-1 text-[10px] opacity-70">
                {new Date(checkpoint.data.approved_at).toLocaleDateString()}
              </span>
            )}
          </Badge>
        )}
      </CardHeader>

      {checkpoint.pending && (
        <CardContent className="space-y-4">
          {isConcept && concepts?.length ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {concepts.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => setSelected(i)}
                    className={cn(
                      "rounded-lg border p-3 text-left transition-all hover:bg-accent/50",
                      selected === i
                        ? "border-primary bg-primary/5 ring-1 ring-primary"
                        : "border-border/50",
                    )}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-sm font-medium">{c.project_name}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {c.tagline}
                        </p>
                      </div>
                      <Badge variant="outline" className="ml-2 shrink-0">
                        #{c.rank}
                      </Badge>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      Score:{" "}
                      <span className="font-medium text-foreground">
                        {c.total_score}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
              <Button
                className="w-full"
                disabled={selected === null}
                onClick={() => {
                  if (selected !== null && concepts[selected]) {
                    onApprove({ selected_concept: concepts[selected] })
                  }
                }}
              >
                <ThumbsUp className="mr-1.5 size-4" />
                Approve Selected Concept
              </Button>
            </>
          ) : (
            <div className="flex gap-2">
              <Button className="flex-1" onClick={() => onApprove()}>
                <ThumbsUp className="mr-1.5 size-4" />
                Approve
              </Button>
              <Button
                variant="destructive"
                className="flex-1"
                onClick={() => onApprove({ rejected: true })}
              >
                <ThumbsDown className="mr-1.5 size-4" />
                Reject
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}
