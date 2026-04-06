"use client"

import { useCallback, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { HackathonTable } from "@/components/hackathon-table"
import { useHackathons } from "@/hooks/use-hackathons"
import { deleteHackathon, rerollHackathon } from "@/lib/api"

export default function HackathonsPage() {
  const { hackathons, isLoading, mutate } = useHackathons()
  const [pendingDelete, setPendingDelete] = useState<string[] | null>(null)

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

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Hackathons</h1>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-lg bg-muted/50"
            />
          ))}
        </div>
      ) : hackathons.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No hackathons found. Scout new ones to get started.
          </CardContent>
        </Card>
      ) : (
        <HackathonTable
          hackathons={hackathons}
          onDelete={handleDelete}
          onReroll={handleReroll}
        />
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
              Delete hackathon{pendingDelete && pendingDelete.length > 1 ? "s" : ""}?
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
            <Button
              variant="destructive"
              onClick={confirmDelete}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
