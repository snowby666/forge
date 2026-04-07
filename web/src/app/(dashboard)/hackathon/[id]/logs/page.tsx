"use client"

import { use } from "react"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import TraceViewer from "@/components/trace-viewer"

export default function LogsPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col space-y-4">
      <div className="flex items-center gap-3">
        <Link href={`/hackathon/${id}`}>
          <Button variant="ghost" size="icon-sm">
            <ArrowLeft className="size-4" />
          </Button>
        </Link>
        <h1 className="text-xl font-bold">Traces</h1>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <TraceViewer hackathonId={id} />
      </div>
    </div>
  )
}
