"use client"

import { useCallback, useState } from "react"
import { Eye, EyeOff, Pencil, Save } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ConfigEntry } from "@/lib/types"

interface ConfigEditorProps {
  entries: ConfigEntry[]
  onSave: (entries: ConfigEntry[]) => void
}

export function ConfigEditor({ entries: initial, onSave }: ConfigEditorProps) {
  const [entries, setEntries] = useState<ConfigEntry[]>(initial)
  const [revealed, setRevealed] = useState<Set<string>>(new Set())
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")
  const [dirty, setDirty] = useState(false)

  const toggleReveal = useCallback((key: string) => {
    setRevealed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const startEdit = useCallback((entry: ConfigEntry) => {
    setEditingKey(entry.key)
    setEditValue(String(entry.value ?? ""))
  }, [])

  const saveEdit = useCallback(() => {
    if (!editingKey) return
    setEntries((prev) =>
      prev.map((e) =>
        e.key === editingKey ? { ...e, value: editValue } : e,
      ),
    )
    setEditingKey(null)
    setDirty(true)
  }, [editingKey, editValue])

  const editingEntry = entries.find((e) => e.key === editingKey)
  const hasEmptyRequired = entries.some(
    (e) => !e.value,
  )

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Key</TableHead>
            <TableHead>Value</TableHead>
            <TableHead className="hidden sm:table-cell">
              Description
            </TableHead>
            <TableHead className="w-[100px]">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((entry) => (
            <TableRow key={entry.key}>
              <TableCell className="font-mono text-xs">
                {entry.key}
                {entry.secret && (
                  <Badge variant="outline" className="ml-2 text-[10px]">
                    secret
                  </Badge>
                )}
              </TableCell>
              <TableCell className="max-w-[200px] truncate font-mono text-xs">
                {entry.secret && !revealed.has(entry.key)
                  ? "•••••••"
                  : String(entry.value ?? "")}
              </TableCell>
              <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
                {entry.description}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1">
                  {entry.secret && (
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => toggleReveal(entry.key)}
                    >
                      {revealed.has(entry.key) ? (
                        <EyeOff className="size-3.5" />
                      ) : (
                        <Eye className="size-3.5" />
                      )}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => startEdit(entry)}
                  >
                    <Pencil className="size-3.5" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {hasEmptyRequired && (
        <p className="text-xs text-yellow-500">Some keys have empty values.</p>
      )}

      <div className="flex justify-end">
        <Button disabled={!dirty} onClick={() => onSave(entries)}>
          <Save className="mr-1.5 size-4" />
          Save Changes
        </Button>
      </div>

      <Dialog
        open={editingKey !== null}
        onOpenChange={(open) => {
          if (!open) setEditingKey(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit {editingKey}</DialogTitle>
          </DialogHeader>
          {editingEntry?.description && (
            <p className="text-xs text-muted-foreground">
              {editingEntry.description}
            </p>
          )}
          <Input
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            type={editingEntry?.secret ? "password" : "text"}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingKey(null)}>
              Cancel
            </Button>
            <Button onClick={saveEdit}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
