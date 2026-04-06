"use client"

import { useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import {
  CheckCircle2,
  ChevronDown,
  Clock,
  Code2,
  Copy,
  FileCheck,
  Layers,
  Palette,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import type { Checkpoint } from "@/lib/types"
import { cn } from "@/lib/utils"

export interface ConceptOption {
  project_name: string
  tagline: string
  total_score: number
  rank: number
  tech_stack?: string[]
  reasoning?: string
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

function scoreColor(score: number) {
  if (score >= 80) return "text-emerald-400"
  if (score >= 60) return "text-yellow-400"
  if (score >= 40) return "text-orange-400"
  return "text-red-400"
}

function scoreBg(score: number) {
  if (score >= 80) return "bg-emerald-500/10 border-emerald-500/20"
  if (score >= 60) return "bg-yellow-500/10 border-yellow-500/20"
  if (score >= 40) return "bg-orange-500/10 border-orange-500/20"
  return "bg-red-500/10 border-red-500/20"
}

const CHECKPOINT_ICON: Record<string, typeof Clock> = {
  concept_approval: Layers,
  design_approval: Palette,
  quality_review: ShieldCheck,
  submission_approval: FileCheck,
}

function RawDataSection({ data }: { data: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  const json = JSON.stringify(data, null, 2)

  return (
    <div className="border-t border-border/40 pt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Code2 className="size-3" />
        Raw Data
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown className="size-3" />
        </motion.span>
        <span className="ml-auto">
          <Button
            variant="ghost"
            size="icon-xs"
            className="size-5"
            onClick={(e) => {
              e.stopPropagation()
              navigator.clipboard.writeText(json)
              toast.success("Copied raw data")
            }}
          >
            <Copy className="size-2.5" />
          </Button>
        </span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
              {json}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function ApprovalDetails({ data }: { data: Record<string, unknown> }) {
  const approvedAt = data.approved_at as string | undefined
  const approvedBy = data.approved_by as string | undefined
  const notes = data.approval_notes as string | undefined

  if (!approvedAt && !approvedBy) return null

  return (
    <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 text-emerald-400">
        <CheckCircle2 className="size-3" />
        <span className="font-medium">Approved</span>
      </div>
      <div className="mt-1 space-y-0.5 text-muted-foreground">
        {approvedBy && <p>By: {approvedBy}</p>}
        {approvedAt && (
          <p>{new Date(approvedAt).toLocaleString()}</p>
        )}
        {notes && <p className="italic">{notes}</p>}
      </div>
    </div>
  )
}

function ConceptApprovalBody({
  checkpoint,
  concepts,
  onApprove,
}: {
  checkpoint: Checkpoint
  concepts?: ConceptOption[]
  onApprove: (data?: Record<string, unknown>) => void
}) {
  const [selected, setSelected] = useState<number | null>(null)
  const items = concepts?.length
    ? concepts
    : (checkpoint.data.concepts as ConceptOption[] | undefined)

  const reasoning = checkpoint.data.reasoning as string | undefined
  const analysis = checkpoint.data.analysis as string | undefined

  if (!checkpoint.pending) {
    return <ApprovalDetails data={checkpoint.data} />
  }

  return (
    <div className="space-y-4">
      {(reasoning || analysis) && (
        <div className="rounded-lg bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
          {reasoning || analysis}
        </div>
      )}

      {items?.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {items.map((c, i) => (
            <motion.button
              key={i}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => setSelected(i)}
              className={cn(
                "rounded-lg border p-3 text-left transition-all",
                selected === i
                  ? "border-primary bg-primary/5 ring-2 ring-primary shadow-lg shadow-primary/5"
                  : "border-border/50 hover:bg-accent/30",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{c.project_name}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                    {c.tagline}
                  </p>
                </div>
                <Badge
                  variant="outline"
                  className="shrink-0 font-mono text-[10px] font-bold"
                >
                  #{c.rank}
                </Badge>
              </div>

              <div className="mt-2 flex items-center justify-between">
                <span className={cn("text-xs font-mono font-bold", scoreColor(c.total_score))}>
                  {c.total_score}/100
                </span>
                <div
                  className={cn(
                    "h-1 flex-1 mx-2 rounded-full overflow-hidden",
                    scoreBg(c.total_score),
                  )}
                >
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      c.total_score >= 80
                        ? "bg-emerald-500"
                        : c.total_score >= 60
                          ? "bg-yellow-500"
                          : c.total_score >= 40
                            ? "bg-orange-500"
                            : "bg-red-500",
                    )}
                    style={{ width: `${c.total_score}%` }}
                  />
                </div>
              </div>

              {c.tech_stack && c.tech_stack.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {c.tech_stack.map((t) => (
                    <Badge key={t} variant="secondary" className="text-[9px]">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
            </motion.button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No concepts available.</p>
      )}

      <div className="flex gap-2">
        <Button
          className="flex-1"
          disabled={selected === null}
          onClick={() => {
            if (selected !== null && items?.[selected]) {
              onApprove({ selected_concept: items[selected] })
            }
          }}
        >
          <ThumbsUp className="mr-1.5 size-4" />
          Approve Selected
        </Button>
        <Button
          variant="destructive"
          onClick={() => onApprove({ rejected: true })}
        >
          <XCircle className="mr-1.5 size-4" />
          Reject All
        </Button>
      </div>
    </div>
  )
}

function DesignApprovalBody({
  checkpoint,
  onApprove,
}: {
  checkpoint: Checkpoint
  onApprove: (data?: Record<string, unknown>) => void
}) {
  const [notes, setNotes] = useState("")
  const summary = checkpoint.data.summary as string | undefined
  const components = checkpoint.data.components as
    | Array<{ name: string; description?: string }>
    | undefined
  const tokens = checkpoint.data.tokens as Record<string, unknown> | undefined
  const colors = (tokens?.colors ?? checkpoint.data.colors) as
    | Record<string, string>
    | undefined

  if (!checkpoint.pending) {
    return <ApprovalDetails data={checkpoint.data} />
  }

  return (
    <div className="space-y-4">
      {summary && (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {summary}
        </p>
      )}

      {components && components.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Components ({components.length})
          </p>
          <div className="grid gap-1.5">
            {components.map((c) => (
              <div
                key={c.name}
                className="flex items-center gap-2 rounded-md border border-border/30 px-2.5 py-1.5 text-xs"
              >
                <Code2 className="size-3 shrink-0 text-muted-foreground" />
                <span className="font-medium">{c.name}</span>
                {c.description && (
                  <span className="truncate text-muted-foreground">
                    — {c.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {colors && Object.keys(colors).length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Color Palette
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(colors).map(([name, value]) => (
              <div key={name} className="flex items-center gap-1.5">
                <div
                  className="size-5 rounded-md border border-border/40"
                  style={{ backgroundColor: value }}
                />
                <span className="text-[10px] text-muted-foreground">{name}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <Textarea
        placeholder="Optional feedback notes..."
        className="min-h-[60px] text-xs"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />

      <div className="flex gap-2">
        <Button
          className="flex-1"
          onClick={() =>
            onApprove(notes ? { approved: true, notes } : { approved: true })
          }
        >
          <ThumbsUp className="mr-1.5 size-4" />
          Approve Design
        </Button>
        <Button
          variant="outline"
          onClick={() =>
            onApprove({ changes_requested: true, notes })
          }
        >
          Request Changes
        </Button>
      </div>
    </div>
  )
}

function QualityReviewBody({
  checkpoint,
  onApprove,
}: {
  checkpoint: Checkpoint
  onApprove: (data?: Record<string, unknown>) => void
}) {
  const [showIssues, setShowIssues] = useState(false)
  const metrics = checkpoint.data.metrics as
    | { test_coverage?: number; lint_errors?: number; security_issues?: number }
    | undefined
  const issues = checkpoint.data.issues as
    | Array<{ severity: string; message: string }>
    | undefined

  if (!checkpoint.pending) {
    return <ApprovalDetails data={checkpoint.data} />
  }

  return (
    <div className="space-y-4">
      {metrics && (
        <div className="grid grid-cols-3 gap-2">
          {metrics.test_coverage !== undefined && (
            <div className="rounded-lg border border-border/30 p-2.5 text-center">
              <p className="text-[10px] text-muted-foreground">Test Coverage</p>
              <p
                className={cn(
                  "mt-0.5 font-mono text-lg font-bold",
                  metrics.test_coverage >= 80
                    ? "text-emerald-400"
                    : metrics.test_coverage >= 50
                      ? "text-yellow-400"
                      : "text-red-400",
                )}
              >
                {metrics.test_coverage}%
              </p>
            </div>
          )}
          {metrics.lint_errors !== undefined && (
            <div className="rounded-lg border border-border/30 p-2.5 text-center">
              <p className="text-[10px] text-muted-foreground">Lint Errors</p>
              <p
                className={cn(
                  "mt-0.5 font-mono text-lg font-bold",
                  metrics.lint_errors === 0 ? "text-emerald-400" : "text-red-400",
                )}
              >
                {metrics.lint_errors}
              </p>
            </div>
          )}
          {metrics.security_issues !== undefined && (
            <div className="rounded-lg border border-border/30 p-2.5 text-center">
              <p className="text-[10px] text-muted-foreground">Security</p>
              <p
                className={cn(
                  "mt-0.5 font-mono text-lg font-bold",
                  metrics.security_issues === 0
                    ? "text-emerald-400"
                    : "text-red-400",
                )}
              >
                {metrics.security_issues}
              </p>
            </div>
          )}
        </div>
      )}

      {issues && issues.length > 0 && (
        <div>
          <button
            onClick={() => setShowIssues(!showIssues)}
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <motion.span
              animate={{ rotate: showIssues ? 180 : 0 }}
              transition={{ duration: 0.2 }}
            >
              <ChevronDown className="size-3" />
            </motion.span>
            {issues.length} issue{issues.length !== 1 && "s"}
          </button>
          <AnimatePresence>
            {showIssues && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="mt-2 max-h-48 space-y-1.5 overflow-auto">
                  {issues.map((issue, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 rounded-md border border-border/30 px-2.5 py-1.5 text-xs"
                    >
                      <Badge
                        variant={
                          issue.severity === "error"
                            ? "destructive"
                            : issue.severity === "warning"
                              ? "outline"
                              : "secondary"
                        }
                        className="mt-0.5 shrink-0 text-[9px]"
                      >
                        {issue.severity}
                      </Badge>
                      <span>{issue.message}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      <div className="flex gap-2">
        <Button className="flex-1" onClick={() => onApprove({ approved: true })}>
          <ThumbsUp className="mr-1.5 size-4" />
          Approve
        </Button>
        <Button
          variant="outline"
          onClick={() => onApprove({ fixes_requested: true })}
        >
          Request Fixes
        </Button>
        <Button
          variant="destructive"
          onClick={() => onApprove({ rejected: true })}
        >
          <ThumbsDown className="mr-1.5 size-4" />
          Reject
        </Button>
      </div>
    </div>
  )
}

function SubmissionApprovalBody({
  checkpoint,
  onApprove,
}: {
  checkpoint: Checkpoint
  onApprove: (data?: Record<string, unknown>) => void
}) {
  const summary = checkpoint.data.summary as string | undefined
  const requirements: Array<{ label: string; key: string }> = [
    { label: "Demo Video", key: "demo_video" },
    { label: "README", key: "readme" },
    { label: "Deployed Link", key: "deployed_link" },
    { label: "Source Code", key: "source_code" },
    { label: "Pitch Deck", key: "pitch_deck" },
    { label: "Screenshots", key: "screenshots" },
  ]

  if (!checkpoint.pending) {
    return <ApprovalDetails data={checkpoint.data} />
  }

  return (
    <div className="space-y-4">
      {summary && (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {summary}
        </p>
      )}

      <div className="space-y-1.5">
        <p className="text-xs font-medium text-muted-foreground">
          Submission Checklist
        </p>
        {requirements.map((req) => {
          const val = checkpoint.data[req.key]
          const present = val !== undefined && val !== null && val !== ""
          return (
            <div
              key={req.key}
              className="flex items-center gap-2 rounded-md border border-border/30 px-2.5 py-1.5 text-xs"
            >
              {present ? (
                <CheckCircle2 className="size-3.5 text-emerald-500" />
              ) : (
                <XCircle className="size-3.5 text-zinc-500" />
              )}
              <span className={present ? "text-foreground" : "text-muted-foreground"}>
                {req.label}
              </span>
              {present && typeof val === "string" && val.startsWith("http") && (
                <a
                  href={val}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto text-[10px] text-primary hover:underline"
                >
                  View
                </a>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex gap-2">
        <Button className="flex-1" onClick={() => onApprove({ submitted: true })}>
          <FileCheck className="mr-1.5 size-4" />
          Submit
        </Button>
        <Button
          variant="outline"
          onClick={() => onApprove({ on_hold: true })}
        >
          <Clock className="mr-1.5 size-4" />
          Hold
        </Button>
      </div>
    </div>
  )
}

function GenericBody({
  checkpoint,
  onApprove,
}: {
  checkpoint: Checkpoint
  onApprove: (data?: Record<string, unknown>) => void
}) {
  if (!checkpoint.pending) {
    return <ApprovalDetails data={checkpoint.data} />
  }

  const json = JSON.stringify(checkpoint.data, null, 2)

  return (
    <div className="space-y-4">
      <pre className="max-h-48 overflow-auto rounded-lg bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
        {json}
      </pre>
      <div className="flex gap-2">
        <Button className="flex-1" onClick={() => onApprove({ approved: true })}>
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
    </div>
  )
}

export function CheckpointCard({
  checkpoint,
  hackathonId,
  concepts,
  onApprove,
}: CheckpointCardProps) {
  const Icon = CHECKPOINT_ICON[checkpoint.checkpoint] ?? Clock

  function renderBody() {
    switch (checkpoint.checkpoint) {
      case "concept_approval":
        return (
          <ConceptApprovalBody
            checkpoint={checkpoint}
            concepts={concepts}
            onApprove={onApprove}
          />
        )
      case "design_approval":
        return (
          <DesignApprovalBody checkpoint={checkpoint} onApprove={onApprove} />
        )
      case "quality_review":
        return (
          <QualityReviewBody checkpoint={checkpoint} onApprove={onApprove} />
        )
      case "submission_approval":
        return (
          <SubmissionApprovalBody
            checkpoint={checkpoint}
            onApprove={onApprove}
          />
        )
      default:
        return (
          <GenericBody checkpoint={checkpoint} onApprove={onApprove} />
        )
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <Card
        className={cn(
          "transition-all",
          checkpoint.pending &&
            "border-yellow-500/50 shadow-md shadow-yellow-500/10",
        )}
      >
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Icon className="size-4 text-muted-foreground" />
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
                    {new Date(
                      checkpoint.data.approved_at as string,
                    ).toLocaleDateString()}
                  </span>
                )}
              </Badge>
            )}
          </div>
          {checkpoint.pending && (
            <CardDescription className="text-xs">
              {checkpoint.checkpoint === "concept_approval" &&
                "Select a concept to approve for this hackathon"}
              {checkpoint.checkpoint === "design_approval" &&
                "Review the proposed design system"}
              {checkpoint.checkpoint === "quality_review" &&
                "Review code quality metrics and issues"}
              {checkpoint.checkpoint === "submission_approval" &&
                "Verify all submission requirements are met"}
            </CardDescription>
          )}
        </CardHeader>

        <CardContent className="space-y-4">
          {renderBody()}
          <RawDataSection data={checkpoint.data} />
        </CardContent>
      </Card>
    </motion.div>
  )
}
