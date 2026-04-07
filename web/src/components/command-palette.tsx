"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Command } from "cmdk"
import {
  BarChart3,
  CheckCircle2,
  LayoutDashboard,
  Play,
  ScrollText,
  Search,
  Settings,
  Terminal,
  Trophy,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { toast } from "sonner"
import { Dialog, DialogContent } from "@/components/ui/dialog"
import { useHackathons } from "@/hooks/use-hackathons"
import { runScout } from "@/lib/api"

interface CommandItemDef {
  id: string
  label: string
  icon: LucideIcon
  href?: string
  action?: () => void
  shortcut?: string
}

const PAGES: CommandItemDef[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, href: "/", shortcut: "⌘D" },
  { id: "hackathons", label: "Hackathons", icon: Trophy, href: "/hackathons" },
  { id: "traces", label: "Live Traces", icon: Terminal, href: "/hackathon" },
  { id: "analytics", label: "Analytics", icon: BarChart3, href: "/analytics" },
  { id: "settings", label: "Settings", icon: Settings, href: "/settings", shortcut: "⌘," },
]

const ACTIONS: CommandItemDef[] = [
  {
    id: "run-scout",
    label: "Run Scout",
    icon: Play,
    action: async () => {
      try {
        const res = await runScout()
        if (res.already_running) {
          toast.info("Scout is already running")
        } else if (res.ok) {
          toast.success("Scout started in background!")
        } else {
          toast.error(res.error ?? "Failed to start scout")
        }
      } catch {
        toast.error("Failed to start scout")
      }
    },
  },
  { id: "view-traces", label: "View Traces", icon: ScrollText, href: "/hackathon" },
  {
    id: "approve-all",
    label: "Approve All Pending",
    icon: CheckCircle2,
    href: "/",
  },
]

const GROUP_HEADING =
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"

const ITEM_CLASS =
  "flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground outline-none select-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const router = useRouter()
  const { hackathons } = useHackathons()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  const hackathonItems = useMemo<CommandItemDef[]>(
    () =>
      hackathons.slice(0, 5).map((h) => ({
        id: `hack-${h.id}`,
        label: h.brief.name,
        icon: Trophy,
        href: `/hackathon/${h.id}`,
      })),
    [hackathons],
  )

  function select(item: CommandItemDef) {
    setOpen(false)
    if (item.href) router.push(item.href)
    else item.action?.()
  }

  function renderItem(item: CommandItemDef) {
    const Icon = item.icon
    return (
      <Command.Item
        key={item.id}
        value={item.label}
        onSelect={() => select(item)}
        className={ITEM_CLASS}
      >
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate">{item.label}</span>
        {item.shortcut && (
          <kbd className="ml-auto shrink-0 rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            {item.shortcut}
          </kbd>
        )}
      </Command.Item>
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        showCloseButton={false}
        className="top-[30%] gap-0 overflow-hidden p-0 sm:max-w-md"
      >
        <Command className="flex h-full w-full flex-col overflow-hidden">
          <div className="flex items-center border-b px-3">
            <Search className="mr-2 size-4 shrink-0 text-muted-foreground" />
            <Command.Input
              placeholder="Search pages, hackathons, actions…"
              className="flex h-10 w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
            />
            <kbd className="ml-2 hidden shrink-0 rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:inline-block">
              ESC
            </kbd>
          </div>
          <Command.List className="max-h-72 overflow-y-auto p-1">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results found.
            </Command.Empty>
            <Command.Group heading="Pages" className={GROUP_HEADING}>
              {PAGES.map(renderItem)}
            </Command.Group>
            {hackathonItems.length > 0 && (
              <>
                <Command.Separator className="mx-1 my-1 h-px bg-border" />
                <Command.Group heading="Hackathons" className={GROUP_HEADING}>
                  {hackathonItems.map(renderItem)}
                </Command.Group>
              </>
            )}
            <Command.Separator className="mx-1 my-1 h-px bg-border" />
            <Command.Group heading="Actions" className={GROUP_HEADING}>
              {ACTIONS.map(renderItem)}
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
