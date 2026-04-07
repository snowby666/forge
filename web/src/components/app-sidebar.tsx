"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import useSWR from "swr"
import {
  LayoutDashboard,
  Trophy,
  BarChart3,
  Settings,
  CircuitBoard,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { Badge } from "@/components/ui/badge"
import { fetchHackathons, fetchCheckpoints } from "@/lib/api"
import type { Hackathon, Checkpoint } from "@/lib/types"

import { Terminal } from "lucide-react"

const navItems = [
  { title: "Dashboard", path: "/", icon: LayoutDashboard },
  { title: "Hackathons", path: "/hackathons", icon: Trophy },
  { title: "Live Traces", path: "/hackathon", icon: Terminal },
  { title: "Analytics", path: "/analytics", icon: BarChart3 },
  { title: "Settings", path: "/settings", icon: Settings },
]

export function AppSidebar() {
  const pathname = usePathname()

  const { data: hackathons } = useSWR<Hackathon[]>("/api/hackathons", fetchHackathons, {
    refreshInterval: 30_000,
    fallbackData: [],
  })

  const { data: checkpoints } = useSWR<Checkpoint[]>("/api/checkpoints", fetchCheckpoints, {
    refreshInterval: 15_000,
    fallbackData: [],
  })

  const pendingCount = checkpoints?.filter((c) => c.pending).length ?? 0
  const activeCount = hackathons?.length ?? 0

  function badgeFor(title: string) {
    if (title === "Dashboard" && pendingCount > 0) return pendingCount
    if (title === "Hackathons" && activeCount > 0) return activeCount
    return null
  }

  return (
    <Sidebar variant="sidebar" collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <div className="flex size-7 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
            <CircuitBoard className="size-4" />
          </div>
          <span className="truncate text-sm font-semibold tracking-tight">
            Forge
          </span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const isActive =
                  item.path === "/"
                    ? pathname === "/"
                    : pathname === item.path ||
                      pathname.startsWith(item.path + "/")

                const count = badgeFor(item.title)

                return (
                  <SidebarMenuItem key={item.path}>
                    <SidebarMenuButton
                      isActive={isActive}
                      tooltip={item.title}
                      render={<Link href={item.path} />}
                    >
                      <item.icon />
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                    {count !== null && (
                      <SidebarMenuBadge>
                        <Badge variant="secondary" className="scale-90">
                          {count}
                        </Badge>
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-sidebar-foreground/60">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
          </span>
          <span className="truncate">Forge v2.0</span>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
