"use client"

import { useState } from "react"
import ReactMarkdown from "react-markdown"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"

interface DesignPreviewProps {
  designMd?: string
  screenshots?: string[]
  tokens?: Record<string, unknown>
  components?: Array<{
    name: string
    description?: string
    demo_critical?: boolean
  }>
}

export function DesignPreview({
  designMd,
  screenshots,
  tokens,
  components,
}: DesignPreviewProps) {
  const [enlarged, setEnlarged] = useState<string | null>(null)

  return (
    <>
      <Tabs defaultValue={0}>
        <TabsList>
          <TabsTrigger value={0}>Design Doc</TabsTrigger>
          <TabsTrigger value={1}>Screenshots</TabsTrigger>
          <TabsTrigger value={2}>Tokens</TabsTrigger>
          <TabsTrigger value={3}>Components</TabsTrigger>
        </TabsList>

        <TabsContent value={0}>
          {designMd ? (
            <div className="prose prose-invert prose-sm max-w-none">
              <ReactMarkdown>{designMd}</ReactMarkdown>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No design document available.
            </p>
          )}
        </TabsContent>

        <TabsContent value={1}>
          {screenshots?.length ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {screenshots.map((url, i) => (
                <button
                  key={i}
                  className="overflow-hidden rounded-lg border border-border/50 transition-transform hover:scale-[1.02]"
                  onClick={() => setEnlarged(url)}
                >
                  <img
                    src={url}
                    alt={`Screenshot ${i + 1}`}
                    className="h-auto w-full object-cover"
                  />
                </button>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No screenshots available.
            </p>
          )}
        </TabsContent>

        <TabsContent value={2}>
          {tokens ? (
            <pre className="overflow-auto rounded-lg bg-zinc-950 p-4 font-mono text-xs leading-6 text-zinc-300">
              {JSON.stringify(tokens, null, 2)}
            </pre>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No tokens available.
            </p>
          )}
        </TabsContent>

        <TabsContent value={3}>
          {components?.length ? (
            <div className="space-y-3">
              {components.map((comp) => (
                <div
                  key={comp.name}
                  className="flex items-start justify-between rounded-lg border border-border/50 p-3"
                >
                  <div>
                    <p className="text-sm font-medium">{comp.name}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {comp.description}
                    </p>
                  </div>
                  {comp.demo_critical && (
                    <Badge variant="destructive" className="ml-2 shrink-0">
                      Demo Critical
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No components defined.
            </p>
          )}
        </TabsContent>
      </Tabs>

      <Dialog
        open={enlarged !== null}
        onOpenChange={(open) => {
          if (!open) setEnlarged(null)
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogTitle className="sr-only">Screenshot Preview</DialogTitle>
          {enlarged && (
            <img
              src={enlarged}
              alt="Enlarged screenshot"
              className="h-auto w-full rounded"
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
