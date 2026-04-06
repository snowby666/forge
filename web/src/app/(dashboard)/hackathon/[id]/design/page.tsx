"use client"

import { use } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DesignPreview } from "@/components/design-preview"
import { fetchDesignArtifacts } from "@/lib/api"
import type { DesignData } from "@/lib/types"

export default function DesignPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)

  const { data, isLoading } = useSWR<DesignData>(
    `/api/hackathon/${id}/design`,
    () => fetchDesignArtifacts(id),
  )

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Link href={`/hackathon/${id}`}>
            <Button variant="ghost" size="sm">
              <ArrowLeft className="mr-1 size-4" />
              Back
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
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-1 size-4" />
            Back
          </Button>
        </Link>
        <h1 className="text-xl font-bold">Design</h1>
      </div>
      <DesignPreview
        designMd={data?.design_md}
        screenshots={data?.screenshots}
        tokens={data?.tokens}
        components={data?.components}
        screens={data?.screens}
        personality={data?.personality}
        critique={data?.critique}
        figmaFileId={data?.figma_file_id}
        stitchScreens={data?.stitch_screens}
      />
    </div>
  )
}
