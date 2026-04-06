"use client"

import { Skeleton } from "@/components/ui/skeleton"

interface LoadingPageProps {
  lines?: number
  cards?: number
}

export function LoadingPage({ lines, cards }: LoadingPageProps) {
  if (lines) {
    return (
      <div className="space-y-3 p-4">
        {Array.from({ length: lines }, (_, i) => (
          <Skeleton
            key={i}
            className="h-4 rounded"
            style={{ width: `${75 - i * 8}%` }}
          />
        ))}
      </div>
    )
  }

  const count = cards ?? 4
  return (
    <div className="grid gap-4 p-4 sm:grid-cols-2">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-32 rounded-xl" />
      ))}
    </div>
  )
}
