import { useEffect, useRef, useState, useCallback } from "react"
import { useParams } from "react-router-dom"
import { Image as ImageIcon, Sparkles, Loader2, Download, RefreshCw, AlertCircle, CheckCircle } from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import EmptyState from "../components/EmptyState"
import ProgressBar from "../components/ProgressBar"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type { ThumbnailVariant } from "../types"

type ThumbnailMode = "single" | "ab_testing"

export default function Thumbnails() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [loading, setLoading] = useState(true)
  const [projectTitle, setProjectTitle] = useState("")
  const [script, setScript] = useState("")
  const [mode, setMode] = useState<ThumbnailMode>("single")
  const [variantCount, setVariantCount] = useState(2)
  const [generating, setGenerating] = useState(false)
  const [genStatus, setGenStatus] = useState<string>("idle")
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState("")
  const [variants, setVariants] = useState<ThumbnailVariant[]>([])
  const [error, setError] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  // Load project title, script, and existing thumbnails on mount
  useEffect(() => {
    if (!projectId) return

    Promise.all([
      api.getProject(projectId).then((p) => setProjectTitle(p.title || p.name)).catch(() => {}),
      api.getScript(projectId).then((s) => setScript(s.text)).catch(() => {}),
      api.getThumbnailStatus(projectId).then((status) => {
        if (status.status === "done" && status.variants.length > 0) {
          setVariants(status.variants)
          setGenStatus("done")
          setProgress(1)
        }
      }).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [projectId])

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      esRef.current?.close()
    }
  }, [])

  const subscribeSSE = useCallback(() => {
    if (!projectId) return
    esRef.current?.close()

    const es = new EventSource(api.thumbnailEventsUrl(projectId))
    esRef.current = es

    es.addEventListener("thumbnail_progress", (e) => {
      try {
        const data = JSON.parse(e.data)
        setGenStatus(data.status ?? "generating")
        setProgress(data.progress ?? 0)
        setProgressMsg(data.message ?? "")
      } catch { /* ignore malformed */ }
    })

    es.addEventListener("thumbnail_complete", (e) => {
      try {
        const data = JSON.parse(e.data)
        setVariants(data.variants ?? [])
        setGenStatus("done")
        setProgress(1)
        setGenerating(false)
        toast("Thumbnail generation complete", "success")
      } catch { /* ignore */ }
      es.close()
    })

    es.addEventListener("thumbnail_failed", (e) => {
      try {
        const data = JSON.parse(e.data)
        const msg = data.error ?? "Thumbnail generation failed"
        setError(msg)
        setGenStatus("failed")
        toast(msg, "error")
      } catch { /* ignore */ }
      setGenerating(false)
      es.close()
    })

    es.addEventListener("error", () => {
      // EventSource will auto-reconnect
    })
  }, [projectId, toast])

  const handleGenerate = async () => {
    if (!projectId || generating) return
    if (!script.trim()) {
      toast("Script is empty — write or load a script first", "error")
      return
    }

    setGenerating(true)
    setGenStatus("analyzing")
    setProgress(0)
    setProgressMsg("Starting analysis...")
    setVariants([])
    setError(null)

    try {
      await api.generateThumbnail(projectId, {
        script,
        mode,
        variant_count: mode === "ab_testing" ? variantCount : 1,
      })
      subscribeSSE()
    } catch (err: any) {
      setGenerating(false)
      setGenStatus("failed")
      setError(err?.message ?? "Failed to start generation")
      toast(err?.message ?? "Failed to start generation", "error")
    }
  }

  // ─── Guard: no project selected ─────────────────────────

  if (!projectId) {
    return (
      <EmptyState
        icon={<ImageIcon />}
        title="No project selected"
        description="Select a project from the Dashboard to generate thumbnails"
      />
    )
  }

  // ─── Loading skeleton ───────────────────────────────────

  if (loading) {
    return (
      <div>
        <PageHeader title="Thumbnail Generator" />
        <div className="animate-pulse space-y-6">
          <div className="h-40 bg-surface-card rounded-xl border border-border" />
          <div className="h-24 bg-surface-card rounded-xl border border-border" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="aspect-video bg-surface-card rounded-xl border border-border" />
            <div className="aspect-video bg-surface-card rounded-xl border border-border" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Thumbnail Generator"}
        description="AI-powered YouTube thumbnail generation with text overlay and A/B variants"
        backTo={`/editor/${projectId}`}
        actions={
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={generating || !script.trim()}
          >
            {generating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {generating ? "Generating..." : "Generate Thumbnail"}
          </button>
        }
      />

      {/* ── Script Input ───────────────────────────────── */}
      <Card className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <ImageIcon className="w-4 h-4 text-accent" />
          <h3 className="text-sm font-semibold text-white font-sans">Script</h3>
        </div>
        <textarea
          className="w-full h-32 bg-surface-hover border border-border rounded-lg p-3 text-sm text-gray-300 font-mono resize-y focus:outline-none focus:border-accent/50 transition-colors"
          value={script}
          onChange={(e) => setScript(e.target.value)}
          placeholder="Enter your video script or paste the full text..."
          disabled={generating}
        />
        <p className="text-xs text-gray-600 mt-2">
          Gemini analyzes the script to suggest a thumbnail composition, colors, and hook text.
        </p>
      </Card>

      {/* ── Mode Configuration ─────────────────────────── */}
      <Card className="mb-6">
        <div className="flex items-center gap-4 mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-400" />
            <span className="text-sm text-gray-400">Mode:</span>
          </div>
          <div className="flex gap-1 bg-surface-hover rounded-lg p-0.5">
            {(["single", "ab_testing"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                disabled={generating}
                className={`px-3 py-1.5 text-xs font-mono rounded-md transition-all ${
                  mode === m
                    ? "bg-accent/20 text-accent border border-accent/30"
                    : "text-gray-500 hover:text-white"
                }`}
              >
                {m === "single" ? "Single" : "A/B Testing"}
              </button>
            ))}
          </div>
        </div>

        {mode === "ab_testing" && (
          <div className="pt-4 border-t border-border">
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-400">Variants:</span>
              <div className="flex gap-1 bg-surface-hover rounded-lg p-0.5">
                {[2, 3].map((n) => (
                  <button
                    key={n}
                    onClick={() => setVariantCount(n)}
                    disabled={generating}
                    className={`px-3 py-1.5 text-xs font-mono rounded-md transition-all ${
                      variantCount === n
                        ? "bg-accent/20 text-accent border border-accent/30"
                        : "text-gray-500 hover:text-white"
                    }`}
                  >
                    {n} variants
                  </button>
                ))}
              </div>
            </div>
            <p className="text-xs text-gray-600 mt-2">
              Each variant uses different text positioning, color accent, and hook phrasing
            </p>
          </div>
        )}

        <p className="text-xs text-gray-600 mt-2">
          {mode === "single"
            ? "Generate one optimized thumbnail based on Gemini's analysis"
            : "Generate multiple variants to test which performs best with your audience"}
        </p>
      </Card>

      {/* ── Progress ───────────────────────────────────── */}
      {generating && (
        <Card className="mb-6">
          <div className="flex items-center gap-3 mb-3">
            <Loader2 className="w-4 h-4 text-accent animate-spin" />
            <span className="text-sm text-gray-300 font-medium capitalize">{genStatus}</span>
            {progressMsg && (
              <span className="text-xs text-gray-500 ml-auto truncate">{progressMsg}</span>
            )}
          </div>
          <ProgressBar progress={progress * 100} />
          <p className="text-xs text-gray-500 mt-2 text-center">
            {Math.round(progress * 100)}%
          </p>
        </Card>
      )}

      {/* ── Error State ────────────────────────────────── */}
      {error && !generating && (
        <Card className="mb-6 border border-red-500/30">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-red-400 font-medium">Generation failed</p>
              <p className="text-xs text-red-400/70 mt-0.5">{error}</p>
            </div>
            <button className="btn-secondary text-xs shrink-0" onClick={handleGenerate}>
              <RefreshCw className="w-3 h-3" />
              Retry
            </button>
          </div>
        </Card>
      )}

      {/* ── Results ────────────────────────────────────── */}
      {variants.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle className="w-4 h-4 text-green-400" />
            <h3 className="text-sm font-semibold text-white font-sans">
              Generated Thumbnail{variants.length > 1 ? "s" : ""}
            </h3>
            <span className="text-xs text-gray-600">
              ({variants.length} variant{variants.length > 1 ? "s" : ""})
            </span>
          </div>

          <div
            className={`grid gap-4 ${
              variants.length > 1 ? "grid-cols-1 md:grid-cols-2" : "grid-cols-1"
            }`}
          >
            {variants.map((v) => (
              <Card key={v.variant} className="p-0 overflow-hidden group">
                <div className="relative aspect-video bg-surface-elevated">
                  <img
                    src={v.url}
                    alt={`Thumbnail variant ${v.variant + 1}`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  <div className="absolute top-2 left-2 px-2 py-0.5 rounded-md bg-black/60 text-[10px] text-gray-300 font-mono">
                    v{v.variant + 1}
                  </div>
                  <a
                    href={v.url}
                    download
                    className="absolute top-2 right-2 p-2 rounded-lg bg-black/60 hover:bg-black/80 text-gray-300 hover:text-white transition-all opacity-0 group-hover:opacity-100"
                    title="Download thumbnail"
                  >
                    <Download className="w-4 h-4" />
                  </a>
                </div>
                <div className="p-2 flex items-center justify-between">
                  <span className="text-xs text-gray-600 font-mono">
                    Variant {v.variant + 1}
                  </span>
                  <span className="text-[10px] text-gray-700">seed: {v.seed}</span>
                </div>
              </Card>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            {variants.map((v) => (
              <a
                key={v.variant}
                href={v.url}
                download
                className="btn-secondary text-xs flex items-center gap-1.5"
              >
                <Download className="w-3 h-3" />
                Download v{v.variant + 1}
              </a>
            ))}
          </div>
        </div>
      )}

      {/* ── Empty State (no results yet) ───────────────── */}
      {!generating && variants.length === 0 && !error && (
        <EmptyState
          icon={<ImageIcon />}
          title="No thumbnail yet"
          description="Enter your script above and click Generate Thumbnail to create one"
        />
      )}
    </div>
  )
}
