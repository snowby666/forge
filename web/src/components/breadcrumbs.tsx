"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Home } from "lucide-react"

const LABELS: Record<string, string> = {
  hackathon: "Hackathon",
  hackathons: "Hackathons",
  analytics: "Analytics",
  settings: "Settings",
  design: "Design",
  logs: "Logs",
  approve: "Approve",
}

function segmentLabel(segment: string) {
  return LABELS[segment] ?? (segment.length > 12 ? segment.slice(0, 12) + "…" : segment)
}

export function Breadcrumbs() {
  const pathname = usePathname()
  const segments = pathname.split("/").filter(Boolean)

  return (
    <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <Link href="/" className="hover:text-foreground transition-colors">
        <Home className="size-3.5" />
      </Link>

      {segments.map((segment, i) => {
        const href = "/" + segments.slice(0, i + 1).join("/")
        const isLast = i === segments.length - 1

        return (
          <span key={href} className="flex items-center gap-1.5">
            <span className="text-muted-foreground/40">/</span>
            {isLast ? (
              <span className="text-foreground font-medium">
                {segmentLabel(segment)}
              </span>
            ) : (
              <Link href={href} className="hover:text-foreground transition-colors">
                {segmentLabel(segment)}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}
