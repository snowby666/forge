"use client"

import { use } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DesignPreview } from "@/components/design-preview"
import { fetchDesignArtifacts } from "@/lib/api"
import type { DesignArtifact } from "@/lib/types"

export default function DesignPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)

  const { data: artifacts, isLoading } = useSWR<DesignArtifact[]>(
    `/api/hackathon/${id}/design`,
    () => fetchDesignArtifacts(id),
  )

  const designDoc = artifacts?.find((a) => a.type === "design_doc")
  const screenshots = artifacts
    ?.filter((a) => a.type === "screenshot")
    .map((a) => a.url ?? a.content ?? "")
    .filter(Boolean)
  const tokensArtifact = artifacts?.find((a) => a.type === "tokens")
  const tokens = tokensArtifact?.content
    ? (() => {
        try {
          return JSON.parse(tokensArtifact.content) as Record<string, unknown>
        } catch {
          return undefined
        }
      })()
    : undefined
  const components = artifacts
    ?.filter((a) => a.type === "component")
    .map((a) => ({
      name: a.name,
      description: a.content ?? "",
      demo_critical: false,
    }))

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Link href={`/hackathon/${id}`}>
            <Button variant="ghost" size="icon-sm">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <h1 className="text-xl font-bold">Design</h1>
        </div>
        <div className="space-y-3">
          <div className="h-8 w-48 animate-pulse rounded bg-muted" />
          <div className="h-64 animate-pulse rounded-lg bg-muted/50" />
        </div>
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
        <h1 className="text-xl font-bold">Design</h1>
      </div>
      <DesignPreview
        designMd={designDoc?.content}
        screenshots={screenshots}
        tokens={tokens}
        components={components}
      />
    </div>
  )
}
