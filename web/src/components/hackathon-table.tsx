"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table"
import {
  ArrowUpDown,
  Download,
  Eye,
  MoreHorizontal,
  RefreshCw,
  Trash2,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { AgentPhaseName, Hackathon } from "@/lib/types"
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
  return `${days}d`
}

interface HackathonTableProps {
  hackathons: Hackathon[]
  onDelete: (ids: string[]) => void
  onReroll: (id: string) => void
}

export function HackathonTable({
  hackathons,
  onDelete,
  onReroll,
}: HackathonTableProps) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [globalFilter, setGlobalFilter] = useState("")

  const columns = useMemo<ColumnDef<Hackathon>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={table.getIsAllPageRowsSelected()}
            onCheckedChange={(checked) =>
              table.toggleAllPageRowsSelected(!!checked)
            }
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(checked) => row.toggleSelected(!!checked)}
          />
        ),
        enableSorting: false,
      },
      {
        accessorFn: (row) => row.brief.name,
        id: "name",
        header: ({ column }) => (
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2"
            onClick={() => column.toggleSorting()}
          >
            Name
            <ArrowUpDown className="ml-1 size-3" />
          </Button>
        ),
        cell: ({ row }) => (
          <Link
            href={`/hackathon/${row.original.id}`}
            className="font-medium hover:underline"
          >
            {row.original.brief.name}
          </Link>
        ),
      },
      {
        accessorFn: (row) => row.brief.score,
        id: "score",
        header: ({ column }) => (
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2"
            onClick={() => column.toggleSorting()}
          >
            Score
            <ArrowUpDown className="ml-1 size-3" />
          </Button>
        ),
        cell: ({ row }) => (
          <span
            className={cn(
              "font-mono font-medium",
              scoreColor(row.original.brief.score),
            )}
          >
            {row.original.brief.score}
          </span>
        ),
      },
      {
        accessorFn: (row) => row.brief.days_until_deadline,
        id: "deadline",
        header: ({ column }) => (
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2"
            onClick={() => column.toggleSorting()}
          >
            Deadline
            <ArrowUpDown className="ml-1 size-3" />
          </Button>
        ),
        cell: ({ row }) => {
          const days = row.original.brief.days_until_deadline
          return (
            <span
              className={cn(
                "text-xs",
                days <= 1
                  ? "text-red-400"
                  : days <= 3
                    ? "text-yellow-400"
                    : "text-muted-foreground",
              )}
            >
              {deadlineLabel(days)}
            </span>
          )
        },
      },
      {
        accessorKey: "phase",
        header: "Phase",
        cell: ({ row }) => (
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] capitalize",
              PHASE_BADGE[row.original.phase],
            )}
          >
            {row.original.phase}
          </Badge>
        ),
      },
      {
        id: "prizes",
        header: "Prizes",
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {row.original.brief.prizes?.length ?? 0}
          </span>
        ),
        meta: { hideOnMobile: true },
      },
      {
        id: "actions",
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" size="icon-xs" />}
            >
              <MoreHorizontal className="size-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                render={
                  <Link href={`/hackathon/${row.original.id}`} />
                }
              >
                <Eye className="size-4" />
                View
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => onReroll(row.original.id)}
              >
                <RefreshCw className="size-4" />
                Reroll
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onClick={() => onDelete([row.original.id])}
              >
                <Trash2 className="size-4" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [onDelete, onReroll],
  )

  const table = useReactTable({
    data: hackathons,
    columns,
    state: { sorting, rowSelection, globalFilter },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getRowId: (row) => row.id,
    globalFilterFn: (row, _columnId, filterValue) =>
      row.original.brief.name
        .toLowerCase()
        .includes(String(filterValue).toLowerCase()),
  })

  const selectedIds = Object.keys(rowSelection)

  function exportCsv() {
    const rows = table.getSelectedRowModel().rows
    const csv = [
      "Name,Score,Phase,Deadline",
      ...rows.map((r) => {
        const b = r.original.brief
        return `"${b.name}",${b.score},${r.original.phase},${b.days_until_deadline}d`
      }),
    ].join("\n")
    const blob = new Blob([csv], { type: "text/csv" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "hackathons.csv"
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Input
          placeholder="Search hackathons…"
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="max-w-xs"
        />
      </div>

      {selectedIds.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-border/50 bg-muted/30 p-2">
          <span className="text-xs text-muted-foreground">
            {selectedIds.length} selected
          </span>
          <Button
            size="xs"
            variant="destructive"
            onClick={() => {
              onDelete(selectedIds)
              setRowSelection({})
            }}
          >
            <Trash2 className="mr-1 size-3" />
            Delete
          </Button>
          <Button size="xs" variant="outline" onClick={exportCsv}>
            <Download className="mr-1 size-3" />
            Export CSV
          </Button>
        </div>
      )}

      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  className={cn(
                    (header.column.columnDef.meta as { hideOnMobile?: boolean })
                      ?.hideOnMobile && "hidden sm:table-cell",
                  )}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-state={row.getIsSelected() ? "selected" : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cn(
                      (
                        cell.column.columnDef.meta as {
                          hideOnMobile?: boolean
                        }
                      )?.hideOnMobile && "hidden sm:table-cell",
                    )}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="h-24 text-center text-muted-foreground"
              >
                No hackathons found.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}
