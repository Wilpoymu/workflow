import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import {
  Scissors,
  Play,
  Download,
  CheckCircle,
  XCircle,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  BookText,
} from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import ProgressBar from "../components/ProgressBar"
import VideoPlayer from "../components/VideoPlayer"
import EmptyState from "../components/EmptyState"
import ScriptSelector from "../components/ScriptSelector"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"

type PageStatus = "idle" | "analyzing" | "ready" | "rendering" | "done" | "failed"

interface Suggestion {
  index: number
  start_sec: number
  end_sec: number
  duration: number
  score: number
  reason: string
  text_preview: string
}

interface ShortFile {
  filename: string
  size_bytes: number
}

interface RenderResult {
  index: number
  filename: string
  success: boolean
  error?: string | null
}

const reasonColors: Record<string, string> = {
  hook: "bg-purple-500/15 text-purple-400 border-purple-500/20",
  "tema-clave": "bg-sky-500/15 text-sky-400 border-sky-500/20",
  "frase-poderosa": "bg-amber-500/15 text-amber-400 border-amber-500/20",
  signo: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  manual: "bg-pink-500/15 text-pink-400 border-pink-500/20",
}

const reasonLabels: Record<string, string> = {
  hook: "Hook",
  "tema-clave": "Tema Clave",
  "frase-poderosa": "Frase Poderosa",
  signo: "Signo",
  manual: "Manual",
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

function formatReason(reason: string): string {
  const key = reason.toLowerCase().replace(/\s+/g, "-")
  return reasonLabels[key] || reason
}

function reasonClass(reason: string): string {
  const key = reason.toLowerCase().replace(/\s+/g, "-")
  return reasonColors[key] || "bg-gray-800 text-gray-300 border-border"
}

export default function Shorts() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [projectTitle, setProjectTitle] = useState("")
  const [status, setStatus] = useState<PageStatus>("idle")
  const [errorMessage, setErrorMessage] = useState("")

  // Analysis
  const [videoName, setVideoName] = useState("")
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [showScriptSelector, setShowScriptSelector] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  // Settings
  const [withSubtitles, setWithSubtitles] = useState(true)
  const [fontSize, setFontSize] = useState(48)

  // Render progress
  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState("")
  const [renderResults, setRenderResults] = useState<RenderResult[]>([])

  // Expanded text state per segment
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const toggleExpanded = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  // Downloads
  const [downloads, setDownloads] = useState<ShortFile[]>([])

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => {
      setProjectTitle(p.title || p.name)
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    loadDownloads()
  }, [projectId])

  const loadDownloads = async () => {
    if (!projectId) return
    try {
      const res = await api.listShorts(projectId)
      setDownloads(res.files)
    } catch {
      // No downloads yet — that's fine
    }
  }

  const handleAnalyze = async () => {
    if (!projectId) return
    setStatus("analyzing")
    setErrorMessage("")
    setSuggestions([])
    setSelected(new Set())
    setRenderResults([])

    try {
      const res = await api.analyzeShorts(projectId)
      setVideoName("")
      setSuggestions(res.suggestions)
      // Pre-select all by default
      setSelected(new Set(res.suggestions.map((s) => s.index)))
      setStatus("ready")
      toast(`Found ${res.suggestions.length} segments`, "success")
    } catch (err: any) {
      setStatus("failed")
      setErrorMessage(err?.message ?? "Failed to analyze segments")
      toast(err?.message ?? "Failed to analyze segments", "error")
    }
  }

  const toggleSelect = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const selectAll = () => {
    setSelected(new Set(suggestions.map((s) => s.index)))
  }

  const deselectAll = () => {
    setSelected(new Set())
  }

  const handleRender = async () => {
    if (!projectId || selected.size === 0) return
    setStatus("rendering")
    setProgress(0)
    setProgressMessage("Starting render...")
    setRenderResults([])

    // Separate manual clips from auto-suggestions
    const manualClips = suggestions
      .filter((s): s is Suggestion & { start_word_idx: number; end_word_idx: number } =>
        s.reason === "manual" && typeof (s as any).start_word_idx === "number"
      )
      .map((s) => ({
        index: s.index,
        start_sec: s.start_sec,
        end_sec: s.end_sec,
        duration: s.duration,
        reason: "manual",
        text_preview: s.text_preview,
        start_word_idx: s.start_word_idx,
        end_word_idx: s.end_word_idx,
      }))

    try {
      const res = await api.renderShorts(projectId, {
        selections: Array.from(selected),
        font_size: fontSize,
        with_subtitles: withSubtitles,
        manual_clips: manualClips,
      })
      setRenderResults(res.results)

      // Simulate progress while we wait
      const total = res.results.length
      let done = 0
      for (const r of res.results) {
        if (r.success) {
          done++
          setProgress((done / total) * 100)
          setProgressMessage(`Rendered ${r.filename || `segment ${r.index}`}`)
        } else {
          done++
          setProgress((done / total) * 100)
          setProgressMessage(`Failed: ${r.error || r.filename || `segment ${r.index}`}`)
        }
      }

      setProgress(100)
      setProgressMessage("Render complete")

      const okCount = res.results.filter((r) => r.success).length
      const failCount = res.results.filter((r) => !r.success).length

      if (failCount === 0) {
        setStatus("done")
        toast(`All ${okCount} shorts rendered successfully`, "success")
      } else if (okCount > 0) {
        setStatus("done")
        toast(`${okCount} rendered, ${failCount} failed`, "info")
      } else {
        setStatus("failed")
        setErrorMessage("All segments failed to render")
        toast("All segments failed to render", "error")
      }

      await loadDownloads()
    } catch (err: any) {
      setStatus("failed")
      setErrorMessage(err?.message ?? "Failed to render shorts")
      toast(err?.message ?? "Failed to render shorts", "error")
    }
  }

  const selectedCount = selected.size
  const segmentedCount = suggestions.length

  const handleScriptSelect = (startSec: number, endSec: number, text: string, startWordIdx: number, endWordIdx: number) => {
    const idx = suggestions.length > 0 ? Math.max(...suggestions.map((s) => s.index)) + 1 : 0
    const duration = endSec - startSec
    const manualSuggestion: Suggestion & { start_word_idx?: number; end_word_idx?: number } = {
      index: idx,
      start_sec: startSec,
      end_sec: endSec,
      duration,
      score: 10,
      reason: "manual",
      text_preview: text,
      start_word_idx: startWordIdx,
      end_word_idx: endWordIdx,
    }
    setSuggestions((prev) => [...prev, manualSuggestion])
    setSelected((prev) => new Set(prev).add(idx))
    setStatus("ready")
    toast(`Added manual segment (${formatTime(startSec)} → ${formatTime(endSec)}, ${Math.round(duration)}s)`, "success")
  }

  if (!projectId) {
    return (
      <EmptyState
        icon={<Scissors />}
        title="No project selected"
        description="Select a project from the Dashboard to create Shorts"
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Shorts Maker"}
        description="Convert video segments to vertical Shorts format"
        backTo={`/workflow/${projectId}`}
        actions={
          status === "done" ? (
            <span className="flex items-center gap-2 text-xs text-green-400 font-mono">
              <CheckCircle className="w-4 h-4" />
              Complete
            </span>
          ) : status === "idle" || status === "analyzing" || status === "ready" ? (
            <div className="flex items-center gap-2">
              <button
                className="btn-secondary"
                onClick={() => setShowScriptSelector(true)}
                disabled={status === "analyzing"}
              >
                <BookText className="w-4 h-4" />
                Manual Selection
              </button>
              <button
                className="btn-primary"
                onClick={handleAnalyze}
                disabled={status === "analyzing"}
              >
                {status === "analyzing" ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Scissors className="w-4 h-4" />
                )}
                {status === "analyzing" ? "Analyzing..." : "Analyze Segments"}
              </button>
            </div>
          ) : undefined
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column */}
        <div className="lg:col-span-2 space-y-6">
          {/* Segments Found */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white font-sans">
                Segments Found
              </h3>
              {videoName && (
                <span className="text-[11px] text-gray-500 font-mono truncate max-w-[200px]">
                  {videoName}
                </span>
              )}
            </div>

            {status === "idle" && (
              <div className="text-center py-10">
                <Scissors className="w-12 h-12 text-gray-800 mx-auto mb-3" />
                <p className="text-sm text-gray-500 font-body mb-4">
                  Analyze your video to find the best segments for Shorts
                </p>
                <button className="btn-primary" onClick={handleAnalyze}>
                  <Scissors className="w-4 h-4" />
                  Analyze Segments
                </button>
              </div>
            )}

            {status === "analyzing" && (
              <div className="text-center py-10">
                <Loader2 className="w-10 h-10 text-accent animate-spin mx-auto mb-3" />
                <p className="text-sm text-gray-400 font-body">Analyzing video for short segments...</p>
              </div>
            )}

            {(status === "ready" || status === "rendering") && suggestions.length > 0 && (
              <>
                {/* Select / Deselect All */}
                <div className="flex items-center gap-3 mb-3">
                  <button
                    className="text-xs text-gray-500 hover:text-accent transition-colors"
                    onClick={selectAll}
                    disabled={status === "rendering"}
                  >
                    Select All
                  </button>
                  <span className="text-gray-700">·</span>
                  <button
                    className="text-xs text-gray-500 hover:text-accent transition-colors"
                    onClick={deselectAll}
                    disabled={status === "rendering"}
                  >
                    Deselect All
                  </button>
                  <span className="text-xs text-gray-500 ml-auto font-mono">
                    {selectedCount} segment{selectedCount !== 1 ? "s" : ""} selected
                  </span>
                </div>

                {/* Segment List */}
                <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                  {suggestions.map((seg) => {
                    const isSelected = selected.has(seg.index)
                    const isExpanded = expanded.has(seg.index)
                    const isLong = seg.text_preview.length > 150
                    return (
                      <label
                        key={seg.index}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                          isSelected
                            ? "border-accent bg-accent/5"
                            : "border-border hover:border-accent/30"
                        } ${status === "rendering" ? "pointer-events-none opacity-60" : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(seg.index)}
                          disabled={status === "rendering"}
                          className="mt-0.5 w-4 h-4 rounded border-border text-accent focus:ring-accent shrink-0"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            <span className="text-xs font-mono text-accent font-medium">
                              {formatTime(seg.start_sec)} → {formatTime(seg.end_sec)}
                            </span>
                            <span className="text-xs font-mono text-gray-600">
                              {seg.duration.toFixed(1)}s
                            </span>
                            <span className="text-xs font-mono text-gray-600">
                              Score: {seg.score.toFixed(2)}
                            </span>
                            <span
                              className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${reasonClass(seg.reason)}`}
                            >
                              {formatReason(seg.reason)}
                            </span>
                          </div>
                          <div className="relative">
                            <p
                              className={`text-sm text-gray-400 font-body cursor-pointer ${
                                isExpanded || !isLong ? "" : "line-clamp-2"
                              }`}
                              onClick={() => toggleExpanded(seg.index)}
                            >
                              {seg.text_preview}
                            </p>
                            {isLong && (
                              <span
                                onClick={() => toggleExpanded(seg.index)}
                                className="text-xs text-accent hover:text-accent-light mt-1 flex items-center gap-1 cursor-pointer"
                              >
                                {isExpanded ? (
                                  <>Show less <ChevronUp className="w-3 h-3" /></>
                                ) : (
                                  <>Show more <ChevronDown className="w-3 h-3" /></>
                                )}
                              </span>
                            )}
                          </div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              </>
            )}

            {status === "failed" && errorMessage && (
              <div className="text-center py-10">
                <AlertCircle className="w-10 h-10 text-red-500/40 mx-auto mb-3" />
                <p className="text-sm text-red-400 font-body mb-2">Analysis failed</p>
                <p className="text-xs text-gray-500 font-mono mb-4">{errorMessage}</p>
                <button className="btn-primary" onClick={handleAnalyze}>
                  <Scissors className="w-4 h-4" />
                  Retry Analysis
                </button>
              </div>
            )}

            {segmentedCount === 0 && (status === "ready" || status === "done") && (
              <div className="text-center py-10">
                <AlertCircle className="w-10 h-10 text-amber-500/40 mx-auto mb-3" />
                <p className="text-sm text-gray-400 font-body">No segments were found</p>
              </div>
            )}
          </Card>

          {/* Progress (during rendering) */}
          {(status === "rendering" || status === "done" || status === "failed") && renderResults.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold text-white mb-4 font-sans">Progress</h3>
              <ProgressBar progress={progress} />
              {progressMessage && (
                <p className="text-xs text-gray-500 mt-2 font-mono">{progressMessage}</p>
              )}

              {/* Per-segment status */}
              <div className="mt-4 space-y-2">
                {renderResults.map((r) => (
                  <div
                    key={r.index}
                    className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface-hover/50"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-gray-400">#{r.index}</span>
                      {r.filename && (
                        <span className="text-xs text-gray-300 truncate max-w-[200px]">
                          {r.filename}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {r.success ? (
                        <span className="flex items-center gap-1 text-xs text-green-400">
                          <CheckCircle className="w-3.5 h-3.5" />
                          Done
                        </span>
                      ) : !r.success && r.error ? (
                        <span className="flex items-center gap-1 text-xs text-red-400" title={r.error}>
                          <XCircle className="w-3.5 h-3.5" />
                          Failed
                        </span>
                      ) : (
                        <span className="text-xs text-gray-600">Pending</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        {/* Right Column */}
        <div className="space-y-4">
          {/* Settings */}
          <Card>
            <h3 className="text-sm font-semibold text-white mb-4 font-sans">Settings</h3>

            <div className="space-y-4">
              {/* Burn Subtitles toggle */}
              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm text-gray-300">Burn Subtitles</span>
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded border-border bg-surface-hover text-accent focus:ring-accent"
                  checked={withSubtitles}
                  onChange={(e) => setWithSubtitles(e.target.checked)}
                  disabled={status === "rendering"}
                />
              </label>

              {/* Font Size slider */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm text-gray-300">Font Size</span>
                  <span className="text-xs font-mono text-accent">{fontSize}px</span>
                </div>
                <input
                  type="range"
                  min="36"
                  max="72"
                  value={fontSize}
                  onChange={(e) => setFontSize(parseInt(e.target.value))}
                  disabled={status === "rendering"}
                  className="w-full h-2 bg-surface-hover rounded-lg appearance-none cursor-pointer"
                  style={{ accentColor: "#2dd4bf" }}
                />
                <div className="flex justify-between text-[11px] text-gray-600 mt-1">
                  <span>36</span>
                  <span>72</span>
                </div>
              </div>
            </div>

            <div className="mt-5 pt-4 border-t border-border">
              <button
                className="btn-primary w-full"
                onClick={handleRender}
                disabled={selectedCount === 0 || status === "rendering"}
              >
                {status === "rendering" ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Rendering...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Render Selected
                  </>
                )}
              </button>
              {selectedCount === 0 && status === "ready" && (
                <p className="text-xs text-gray-600 text-center mt-2">
                  Select at least one segment to render
                </p>
              )}
            </div>
          </Card>

          {/* Downloads */}
          <Card>
            <h3 className="text-sm font-semibold text-white mb-4 font-sans">Downloads</h3>

            {downloads.length === 0 ? (
              <p className="text-xs text-gray-600 text-center py-6 font-body">
                {status === "done"
                  ? "No downloadable files yet"
                  : "Rendered shorts will appear here"}
              </p>
            ) : (
              <>
                {/* Preview of first short */}
                {downloads.length > 0 && status === "done" && (
                  <div className="mb-4">
                    <VideoPlayer
                      src={api.shortsDownloadUrl(projectId!, downloads[0].filename)}
                      className="aspect-[9/16] max-h-[400px] mx-auto"
                    />
                  </div>
                )}

                {/* File list */}
                <div className="space-y-2">
                  {downloads.map((f) => (
                    <div
                      key={f.filename}
                      className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface-hover/50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-gray-300 font-mono truncate">{f.filename}</p>
                        <p className="text-[11px] text-gray-600">{(f.size_bytes / 1024 / 1024).toFixed(1)} MB</p>
                      </div>
                      <a
                        href={api.shortsDownloadUrl(projectId!, f.filename)}
                        download
                        className="text-accent hover:text-accent-light transition-colors p-1"
                      >
                        <Download className="w-4 h-4" />
                      </a>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Card>

          {/* Status badge */}
          <Card>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider font-sans">
                Status
              </span>
              {status === "done" ? (
                <span className="flex items-center gap-1.5 text-xs text-green-400 font-mono">
                  <CheckCircle className="w-3.5 h-3.5" />
                  Complete
                </span>
              ) : status === "failed" ? (
                <span className="flex items-center gap-1.5 text-xs text-red-400 font-mono">
                  <AlertCircle className="w-3.5 h-3.5" />
                  Failed
                </span>
              ) : status === "rendering" ? (
                <span className="flex items-center gap-1.5 text-xs text-accent font-mono">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Rendering
                </span>
              ) : status === "analyzing" ? (
                <span className="flex items-center gap-1.5 text-xs text-accent font-mono">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Analyzing
                </span>
              ) : status === "ready" ? (
                <span className="text-xs text-green-400 font-mono">Ready</span>
              ) : (
                <span className="text-xs text-gray-500 font-mono">Idle</span>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Script Selection Modal */}
      {showScriptSelector && projectId && (
        <ScriptSelector
          projectId={projectId}
          onSelect={handleScriptSelect}
          onClose={() => setShowScriptSelector(false)}
        />
      )}
    </div>
  )
}
