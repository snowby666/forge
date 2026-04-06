"use client"

import { useMemo, useState } from "react"
import ReactMarkdown from "react-markdown"
import { motion } from "framer-motion"
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Clock,
  Code2,
  ExternalLink,
  Layers,
  Monitor,
  Sparkles,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import type {
  DesignComponent,
  DesignCritique,
  DesignScreen,
  StitchScreen,
} from "@/lib/types"

interface DesignPreviewProps {
  designMd?: string
  screenshots?: string[]
  tokens?: Record<string, unknown>
  components?: DesignComponent[]
  screens?: DesignScreen[]
  personality?: string
  critique?: DesignCritique
  figmaFileId?: string
  stitchScreens?: StitchScreen[]
}

function ScoreBar({ score, max = 10 }: { score: number; max?: number }) {
  const pct = Math.min((score / max) * 100, 100)
  const color =
    pct >= 70 ? "from-emerald-500 to-emerald-400" :
    pct >= 40 ? "from-yellow-500 to-amber-400" :
    "from-red-500 to-orange-400"

  return (
    <div className="flex items-center gap-3">
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
        <motion.div
          className={`h-full rounded-full bg-gradient-to-r ${color}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
      <span className="shrink-0 font-mono text-sm font-bold tabular-nums">
        {score}/{max}
      </span>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 px-4 py-3 text-center">
      <p className="text-2xl font-bold tabular-nums">{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
    </div>
  )
}

function ScreenCard({
  screen,
  stitchImage,
}: {
  screen: DesignScreen
  stitchImage?: StitchScreen
}) {
  const [open, setOpen] = useState(false)

  return (
    <Card
      className="cursor-pointer transition-colors hover:bg-accent/30"
      onClick={() => setOpen(!open)}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="text-sm">{screen.name}</CardTitle>
            <p className="mt-0.5 font-mono text-xs text-muted-foreground">
              {screen.route}
            </p>
          </div>
          <ChevronDown
            className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {screen.purpose && (
          <p className="text-xs text-muted-foreground">{screen.purpose}</p>
        )}
        {screen.primary_action && (
          <Badge variant="outline" className="text-[10px]">
            {screen.primary_action}
          </Badge>
        )}

        {open && (
          <div className="space-y-3 pt-2">
            {stitchImage && (
              <img
                src={stitchImage.image_url}
                alt={stitchImage.screen_name}
                className="w-full rounded-lg border border-border/50"
              />
            )}
            {screen.secondary_actions && screen.secondary_actions.length > 0 && (
              <div>
                <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Secondary Actions
                </p>
                <div className="flex flex-wrap gap-1">
                  {screen.secondary_actions.map((a) => (
                    <Badge key={a} variant="secondary" className="text-[10px]">
                      {a}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {screen.information_hierarchy && screen.information_hierarchy.length > 0 && (
              <div>
                <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Information Hierarchy
                </p>
                <ol className="list-inside list-decimal space-y-0.5 text-xs text-muted-foreground">
                  {screen.information_hierarchy.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ComponentCard({ component }: { component: DesignComponent }) {
  const [open, setOpen] = useState(false)
  const hasExpandable =
    (component.variants && component.variants.length > 0) ||
    (component.states && component.states.length > 0) ||
    component.props_interface

  return (
    <Card>
      <CardHeader className="pb-2">
        <button
          className="flex w-full items-start justify-between gap-2 text-left"
          onClick={() => hasExpandable && setOpen(!open)}
        >
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm">{component.name}</CardTitle>
              {component.is_demo_critical && (
                <Badge variant="destructive" className="text-[10px]">
                  Demo Critical
                </Badge>
              )}
              {component.shadcn_base && (
                <Badge variant="secondary" className="text-[10px]">
                  {component.shadcn_base}
                </Badge>
              )}
            </div>
            {component.file_path && (
              <p className="font-mono text-[11px] text-muted-foreground">
                {component.file_path}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {component.estimated_minutes != null && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Clock className="size-3" />
                {component.estimated_minutes}m
              </span>
            )}
            {hasExpandable && (
              <ChevronDown
                className={`size-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
              />
            )}
          </div>
        </button>
      </CardHeader>
      <CardContent className="space-y-2">
        {component.purpose && (
          <p className="text-xs text-muted-foreground">{component.purpose}</p>
        )}
        {component.description && !component.purpose && (
          <p className="text-xs text-muted-foreground">{component.description}</p>
        )}

        {open && (
          <div className="space-y-4 pt-2">
            {component.variants && component.variants.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Variants
                </p>
                <div className="overflow-auto rounded-lg border border-border/50">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border/50 bg-muted/30">
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                          Name
                        </th>
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                          Description
                        </th>
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                          Classes
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {component.variants.map((v) => (
                        <tr key={v.name} className="border-b border-border/30 last:border-0">
                          <td className="px-3 py-1.5 font-medium">{v.name}</td>
                          <td className="px-3 py-1.5 text-muted-foreground">
                            {v.description}
                          </td>
                          <td className="px-3 py-1.5">
                            <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
                              {v.tailwind_classes}
                            </code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {component.states && component.states.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  States
                </p>
                <div className="overflow-auto rounded-lg border border-border/50">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border/50 bg-muted/30">
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                          State
                        </th>
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                          Description
                        </th>
                        <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                          Classes
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {component.states.map((s) => (
                        <tr key={s.state} className="border-b border-border/30 last:border-0">
                          <td className="px-3 py-1.5 font-medium">{s.state}</td>
                          <td className="px-3 py-1.5 text-muted-foreground">
                            {s.description}
                          </td>
                          <td className="px-3 py-1.5">
                            <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
                              {s.tailwind_classes}
                            </code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {component.props_interface && (
              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Props Interface
                </p>
                <pre className="overflow-auto rounded-lg bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-300">
                  {component.props_interface}
                </pre>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function TokenSection({ tokens }: { tokens: Record<string, unknown> }) {
  const colors = tokens.colors as Record<string, string> | undefined
  const spacing = tokens.spacing as Record<string, string> | undefined
  const typography = tokens.typography as Record<string, unknown> | undefined
  const radii = tokens.radii as Record<string, string> | undefined

  const hasStructured = colors || spacing || typography || radii
  const otherKeys = Object.keys(tokens).filter(
    (k) => !["colors", "spacing", "typography", "radii"].includes(k),
  )

  return (
    <div className="space-y-6">
      {colors && (
        <div>
          <h3 className="mb-3 text-sm font-medium">Colors</h3>
          <div className="flex flex-wrap gap-3">
            {Object.entries(colors).map(([name, value]) => (
              <div key={name} className="flex items-center gap-2 rounded-lg border border-border/50 px-3 py-2">
                <span
                  className="size-5 shrink-0 rounded-full border border-border/50"
                  style={{ backgroundColor: typeof value === "string" ? value : undefined }}
                />
                <div>
                  <p className="text-xs font-medium">{name}</p>
                  <p className="font-mono text-[10px] text-muted-foreground">
                    {String(value)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {spacing && (
        <div>
          <h3 className="mb-3 text-sm font-medium">Spacing</h3>
          <TokenTable data={spacing} />
        </div>
      )}

      {typography && (
        <div>
          <h3 className="mb-3 text-sm font-medium">Typography</h3>
          <TokenTable data={typography as Record<string, string>} />
        </div>
      )}

      {radii && (
        <div>
          <h3 className="mb-3 text-sm font-medium">Border Radii</h3>
          <TokenTable data={radii} />
        </div>
      )}

      {otherKeys.length > 0 && (
        <div>
          {hasStructured && <h3 className="mb-3 text-sm font-medium">Other</h3>}
          <pre className="overflow-auto rounded-lg bg-zinc-950 p-4 font-mono text-xs leading-6 text-zinc-300">
            {JSON.stringify(
              Object.fromEntries(otherKeys.map((k) => [k, tokens[k]])),
              null,
              2,
            )}
          </pre>
        </div>
      )}

      {!hasStructured && otherKeys.length === 0 && (
        <pre className="overflow-auto rounded-lg bg-zinc-950 p-4 font-mono text-xs leading-6 text-zinc-300">
          {JSON.stringify(tokens, null, 2)}
        </pre>
      )}
    </div>
  )
}

function TokenTable({ data }: { data: Record<string, string> }) {
  return (
    <div className="overflow-auto rounded-lg border border-border/50">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/50 bg-muted/30">
            <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
              Token
            </th>
            <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([key, value]) => (
            <tr key={key} className="border-b border-border/30 last:border-0">
              <td className="px-3 py-1.5 font-mono font-medium">{key}</td>
              <td className="px-3 py-1.5 font-mono text-muted-foreground">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function DesignPreview({
  designMd,
  screenshots,
  tokens,
  components,
  screens,
  personality,
  critique,
  figmaFileId,
  stitchScreens,
}: DesignPreviewProps) {
  const [enlarged, setEnlarged] = useState<string | null>(null)

  const sortedComponents = useMemo(() => {
    if (!components) return []
    return [...components].sort((a, b) => {
      if (a.is_demo_critical && !b.is_demo_critical) return -1
      if (!a.is_demo_critical && b.is_demo_critical) return 1
      return a.name.localeCompare(b.name)
    })
  }, [components])

  const demoCriticalCount = components?.filter((c) => c.is_demo_critical).length ?? 0

  const stitchMap = useMemo(() => {
    const map = new Map<string, StitchScreen>()
    stitchScreens?.forEach((s) => map.set(s.screen_name, s))
    return map
  }, [stitchScreens])

  const allScreenshots = useMemo(() => {
    const items: Array<{ url: string; label?: string }> = []
    stitchScreens?.forEach((s) =>
      items.push({ url: s.image_url, label: s.screen_name }),
    )
    screenshots?.forEach((url, i) => {
      if (!items.some((item) => item.url === url)) {
        items.push({ url, label: `Screenshot ${i + 1}` })
      }
    })
    return items
  }, [screenshots, stitchScreens])

  return (
    <>
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">
            <Sparkles className="mr-1.5 size-3.5" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="screens">
            <Monitor className="mr-1.5 size-3.5" />
            Screens
            {screens && screens.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 size-5 justify-center rounded-full p-0 text-[10px]">
                {screens.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="components">
            <Layers className="mr-1.5 size-3.5" />
            Components
            {components && components.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 size-5 justify-center rounded-full p-0 text-[10px]">
                {components.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="design-doc">
            <Code2 className="mr-1.5 size-3.5" />
            Design Doc
          </TabsTrigger>
          <TabsTrigger value="tokens">Tokens</TabsTrigger>
          <TabsTrigger value="screenshots">
            Screenshots
            {allScreenshots.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 size-5 justify-center rounded-full p-0 text-[10px]">
                {allScreenshots.length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="mt-4 space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Screens" value={screens?.length ?? 0} />
            <StatCard label="Components" value={components?.length ?? 0} />
            <StatCard label="Demo Critical" value={demoCriticalCount} />
            <StatCard label="Screenshots" value={allScreenshots.length} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Design Identity</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {personality && (
                  <div>
                    <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Personality
                    </p>
                    <Badge className="text-sm">{personality}</Badge>
                  </div>
                )}
                {figmaFileId && (
                  <div>
                    <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Figma
                    </p>
                    <a
                      href={`https://www.figma.com/file/${figmaFileId}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Button variant="outline" size="sm">
                        <ExternalLink className="mr-1.5 size-3.5" />
                        Open in Figma
                      </Button>
                    </a>
                  </div>
                )}
                {!personality && !figmaFileId && (
                  <p className="text-xs text-muted-foreground">
                    No identity info available.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Self-Critique</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {critique?.overall_score != null ? (
                  <ScoreBar score={critique.overall_score} />
                ) : (
                  <p className="text-xs text-muted-foreground">No score available.</p>
                )}
                {critique?.strengths && critique.strengths.length > 0 && (
                  <div className="space-y-1.5">
                    {critique.strengths.map((s, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                        <span>{s}</span>
                      </div>
                    ))}
                  </div>
                )}
                {critique?.issues && critique.issues.length > 0 && (
                  <div className="space-y-1.5">
                    {critique.issues.map((issue, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-red-500" />
                        <span>{issue}</span>
                      </div>
                    ))}
                  </div>
                )}
                {!critique && (
                  <p className="text-xs text-muted-foreground">
                    No critique available.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Screens Tab */}
        <TabsContent value="screens" className="mt-4">
          {screens && screens.length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {screens.map((screen) => (
                <ScreenCard
                  key={screen.route}
                  screen={screen}
                  stitchImage={stitchMap.get(screen.name)}
                />
              ))}
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No screens defined.
            </p>
          )}
        </TabsContent>

        {/* Components Tab */}
        <TabsContent value="components" className="mt-4">
          {sortedComponents.length > 0 ? (
            <div className="space-y-3">
              {sortedComponents.map((comp) => (
                <ComponentCard key={comp.name} component={comp} />
              ))}
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No components defined.
            </p>
          )}
        </TabsContent>

        {/* Design Doc Tab */}
        <TabsContent value="design-doc" className="mt-4">
          {designMd ? (
            <div className="prose prose-invert prose-sm max-w-none prose-headings:font-semibold prose-a:text-blue-400 prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:text-[13px] prose-pre:bg-zinc-950 prose-pre:text-zinc-300">
              <ReactMarkdown>{designMd}</ReactMarkdown>
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No design document available.
            </p>
          )}
        </TabsContent>

        {/* Tokens Tab */}
        <TabsContent value="tokens" className="mt-4">
          {tokens && Object.keys(tokens).length > 0 ? (
            <TokenSection tokens={tokens} />
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No tokens available.
            </p>
          )}
        </TabsContent>

        {/* Screenshots Tab */}
        <TabsContent value="screenshots" className="mt-4">
          {allScreenshots.length > 0 ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {allScreenshots.map((item, i) => (
                <button
                  key={i}
                  className="group overflow-hidden rounded-lg border border-border/50 transition-transform hover:scale-[1.02]"
                  onClick={() => setEnlarged(item.url)}
                >
                  <img
                    src={item.url}
                    alt={item.label ?? `Screenshot ${i + 1}`}
                    className="h-auto w-full object-cover"
                  />
                  {item.label && (
                    <p className="border-t border-border/50 bg-muted/30 px-2 py-1.5 text-center text-[11px] text-muted-foreground">
                      {item.label}
                    </p>
                  )}
                </button>
              ))}
            </div>
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No screenshots available.
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
