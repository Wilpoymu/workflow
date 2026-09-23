import { useEffect, useState } from "react"
import { useParams, Link } from "react-router-dom"
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
  Sparkles,
  RefreshCw,
  Clock,
  Zap,
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
  ai_hook?: string
  ai_category?: string
  ai_viral_potential?: string
}

type AnalysisMode = "ai" | "rules" | "combined"

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

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

function scoreColor(score: number): string {
  if (score >= 8) return "text-green-400"
  if (score >= 6) return "text-yellow-400"
  return "text-red-400"
}

function scoreBg(score: number): string {
  if (score >= 8) return "bg-green-500/10 border-green-500/20"
  if (score >= 6) return "bg-yellow-500/10 border-yellow-500/20"
  return "bg-red-500/10 border-red-500/20"
}

function hookColor(hook?: string): string {
  if (hook === "alto") return "text-green-400 bg-green-500/10 border-green-500/20"
  if (hook === "medio") return "text-yellow-400 bg-yellow-500/10 border-yellow-500/20"
  return "text-red-400 bg-red-500/10 border-red-500/20"
}

function viralColor(viral?: string): string {
  if (viral === "alto") return "text-rose-400 bg-rose-500/10 border-rose-500/20"
  if (viral === "medio") return "text-orange-400 bg-orange-500/10 border-orange-500/20"
  return "text-gray-400 bg-gray-500/10 border-gray-500/20"
}

const categoryColors: Record<string, string> = {
  hook: "bg-purple-500/15 text-purple-400 border-purple-500/20",
  "tema-clave": "bg-sky-500/15 text-sky-400 border-sky-500/20",
  "frase-poderosa": "bg-amber-500/15 text-amber-400 border-amber-500/20",
  manual: "bg-pink-500/15 text-pink-400 border-pink-500/20",
  intro: "bg-blue-500/15 text-blue-400 border-blue-500/20",
}

export default function Shorts() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [projectTitle, setProjectTitle] = useState("")
  const [status, setStatus] = useState<PageStatus>("idle")
  const [errorMessage, setErrorMessage] = useState("")

  const [videoName, setVideoName] = useState("")
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [showScriptSelector, setShowScriptSelector] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const [withSubtitles, setWithSubtitles] = useState(true)
  const [fontSize, setFontSize] = useState(48)
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("ai")

  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState("")
  const [renderResults, setRenderResults] = useState<RenderResult[]>([])

  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const [metadataLoading, setMetadataLoading] = useState<number | null>(null)
  const [existingMetadata, setExistingMetadata] = useState<Set<string>>(new Set())

  const [analysisGeneratedAt, setAnalysisGeneratedAt] = useState<string | null>(null)
  const [analysisCached, setAnalysisCached] = useState(false)

  const [downloads, setDownloads] = useState<ShortFile[]>([])

  const toggleExpanded = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

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
    loadExistingMetadata()
    loadCachedAnalysis()
  }, [projectId])

  const loadCachedAnalysis = async () => {
    if (!projectId) return
    try {
      const res = await api.getCachedShortsAnalysis(projectId)
      if (res.suggestions && res.suggestions.length > 0) {
        setSuggestions(res.suggestions)
        setSelected(new Set(res.suggestions.map((s) => s.index)))
        setAnalysisGeneratedAt(res.generated_at)
        setAnalysisCached(true)
        setAnalysisMode(res.mode as AnalysisMode)
        setStatus("ready")
      }
    } catch {
      // No cache yet
    }
  }

  const loadExistingMetadata = async () => {
    if (!projectId) return
    try {
      const res = await api.getShortsMetadata(projectId)
      if (res.metadata && typeof res.metadata === "object") {
        setExistingMetadata(new Set(Object.keys(res.metadata)))
      }
    } catch {}
  }

  const loadDownloads = async () => {
    if (!projectId) return
    try {
      const res = await api.listShorts(projectId)
      setDownloads(res.files)
    } catch {}
  }

  const formatDate = (iso: string | null) => {
    if (!iso) return ""
    const d = new Date(iso)
    return d.toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
  }

  const handleAnalyze = async (forceRefresh: boolean = false) => {
    if (!projectId) return
    setStatus("analyzing")
    setErrorMessage("")
    setSuggestions([])
    setSelected(new Set())
    setRenderResults([])
    setAnalysisCached(false)
    setAnalysisGeneratedAt(null)

    try {
      const res = await api.analyzeShorts(projectId, analysisMode, forceRefresh)
      setVideoName("")
      setSuggestions(res.suggestions)
      setSelected(new Set(res.suggestions.map((s) => s.index)))
      setAnalysisCached(res.cached)
      setAnalysisGeneratedAt(res.generated_at ?? null)
      setStatus("ready")
      const modeLabel = analysisMode === "ai" ? "AI" : analysisMode === "combined" ? "AI+Reglas" : "Reglas"
      const count = res.cached ? " (cargado de caché)" : ""
      toast(`${res.suggestions.length} segmentos encontrados [${modeLabel}]${count}`, "success")
    } catch (err: any) {
      setStatus("failed")
      setErrorMessage(err?.message ?? "Failed to analyze segments")
      toast(err?.message ?? "Error", "error")
    }
  }

  const toggleSelect = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const selectAll = () => setSelected(new Set(suggestions.map((s) => s.index)))
  const deselectAll = () => setSelected(new Set())

  const handleRender = async () => {
    if (!projectId || selected.size === 0) return
    setStatus("rendering")
    setProgress(0)
    setProgressMessage("Iniciando render...")
    setRenderResults([])

    const manualClips = suggestions
      .filter((s): s is Suggestion & { start_word_idx: number; end_word_idx: number } =>
        s.reason === "manual" && typeof (s as any).start_word_idx === "number"
      )
      .map((s) => ({
        index: s.index, start_sec: s.start_sec, end_sec: s.end_sec,
        duration: s.duration, reason: "manual", text_preview: s.text_preview,
        start_word_idx: s.start_word_idx, end_word_idx: s.end_word_idx,
      }))

    try {
      const res = await api.renderShorts(projectId, {
        selections: Array.from(selected),
        font_size: fontSize,
        with_subtitles: withSubtitles,
        manual_clips: manualClips,
      })
      setRenderResults(res.results)

      const total = res.results.length
      let done = 0
      for (const r of res.results) {
        done++
        setProgress((done / total) * 100)
        setProgressMessage(r.success ? `Renderizado ${r.filename}` : `Falló: ${r.error || r.filename}`)
      }
      setProgress(100)
      setProgressMessage("Render completo")

      const okCount = res.results.filter((r) => r.success).length
      const failCount = res.results.filter((r) => !r.success).length
      if (failCount === 0) {
        setStatus("done")
        toast(`Todos los ${okCount} shorts renderizados`, "success")
      } else if (okCount > 0) {
        setStatus("done")
        toast(`${okCount} renderizados, ${failCount} fallaron`, "info")
      } else {
        setStatus("failed")
        setErrorMessage("Todos fallaron")
        toast("Todos los segmentos fallaron", "error")
      }
      await loadDownloads()
    } catch (err: any) {
      setStatus("failed")
      setErrorMessage(err?.message ?? "Failed to render")
      toast(err?.message ?? "Error", "error")
    }
  }

  const handleGenerateShortMetadata = async (index: number, text: string) => {
    if (!projectId) return
    setMetadataLoading(index)
    try {
      await api.generateShortsMetadata(projectId, { index: String(index), text, platform: "both" })
      setExistingMetadata((prev) => new Set(prev).add(String(index)))
      toast("Metadata generada", "success")
    } catch (err: any) {
      toast(err?.message ?? "Error", "error")
    } finally {
      setMetadataLoading(null)
    }
  }

  const handleScriptSelect = (startSec: number, endSec: number, text: string, startWordIdx: number, endWordIdx: number) => {
    const idx = suggestions.length > 0 ? Math.max(...suggestions.map((s) => s.index)) + 1 : 0
    const duration = endSec - startSec
    const manualSuggestion: Suggestion & { start_word_idx?: number; end_word_idx?: number } = {
      index: idx, start_sec: startSec, end_sec: endSec, duration,
      score: 10, reason: "manual", text_preview: text,
      start_word_idx: startWordIdx, end_word_idx: endWordIdx,
    }
    setSuggestions((prev) => [...prev, manualSuggestion])
    setSelected((prev) => new Set(prev).add(idx))
    setStatus("ready")
    toast(`Segmento manual añadido (${formatTime(startSec)} → ${formatTime(endSec)}, ${Math.round(duration)}s)`, "success")
  }

  if (!projectId) {
    return (
      <EmptyState icon={<Scissors />} title="No project selected"
        description="Select a project from the Dashboard to create Shorts" />
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Shorts Maker"}
        description="Convierte segmentos de video a formato vertical Shorts"
        backTo={`/workflow/${projectId}`}
        actions={
          <div className="flex items-center gap-2">
            <button className="btn-secondary" onClick={() => setShowScriptSelector(true)}
              disabled={status === "analyzing" || status === "rendering"}>
              <BookText className="w-4 h-4" /> Manual
            </button>
            {suggestions.length > 0 && analysisCached ? (
              <button className="btn-primary" onClick={() => handleAnalyze(true)}
                disabled={status === "analyzing"}>
                {status === "analyzing" ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Re-Analizar
              </button>
            ) : (
              <button className="btn-primary" onClick={() => handleAnalyze(false)}
                disabled={status === "analyzing"}>
                {status === "analyzing" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Scissors className="w-4 h-4" />}
                {status === "analyzing" ? "Analizando..." : `Analizar (${analysisMode === "ai" ? "AI" : analysisMode === "combined" ? "AI+R" : "Reglas"})`}
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main column */}
        <div className="lg:col-span-2 space-y-6">
          {/* Analysis status bar */}
          {analysisGeneratedAt && (
            <div className="flex items-center gap-3 px-4 py-2 rounded-lg bg-surface-hover/50 border border-border text-xs text-gray-500">
              <Clock className="w-3.5 h-3.5" />
              <span>Análisis {analysisCached ? "en caché" : "generado"}: {formatDate(analysisGeneratedAt)}</span>
              <span className="text-gray-700">·</span>
              <span className="font-mono text-accent">Modo: {analysisMode === "ai" ? "AI" : analysisMode === "combined" ? "AI+Reglas" : "Reglas"}</span>
              {analysisCached && (
                <>
                  <span className="text-gray-700">·</span>
                  <button onClick={() => handleAnalyze(true)}
                    className="text-accent hover:text-accent-light transition-colors flex items-center gap-1">
                    <RefreshCw className="w-3 h-3" /> Re-analizar
                  </button>
                </>
              )}
            </div>
          )}

          {/* Segments */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-foreground dark:text-white font-sans">Segmentos</h3>
              {suggestions.length > 0 && (
                <span className="text-xs text-gray-500 font-mono">{suggestions.length} encontrados</span>
              )}
              )}
            </div>

            {status === "idle" && !analysisCached && (
              <div className="text-center py-10">
                <Scissors className="w-12 h-12 text-gray-800 mx-auto mb-3" />
                <p className="text-sm text-gray-500 font-body mb-4">
                  Analiza tu video para encontrar los mejores segmentos para Shorts
                </p>
                <button className="btn-primary" onClick={() => handleAnalyze(false)}>
                  <Scissors className="w-4 h-4" /> Analizar Segmentos
                </button>
              </div>
            )}

            {status === "analyzing" && (
              <div className="text-center py-10">
                <Loader2 className="w-10 h-10 text-accent animate-spin mx-auto mb-3" />
                <p className="text-sm text-gray-400 font-body">Analizando video con IA...</p>
              </div>
            )}

            {suggestions.length > 0 && (status === "ready" || status === "rendering" || status === "failed") && (
              <>
                <div className="flex items-center gap-3 mb-3">
                  <button className="text-xs text-gray-500 hover:text-accent transition-colors"
                    onClick={selectAll} disabled={status === "rendering"}>
                    Seleccionar Todos
                  </button>
                  <span className="text-gray-700">·</span>
                  <button className="text-xs text-gray-500 hover:text-accent transition-colors"
                    onClick={deselectAll} disabled={status === "rendering"}>
                    Deseleccionar
                  </button>
                  <span className="text-gray-700">·</span>
                  <span className="text-xs text-gray-600">{selected.size}/{suggestions.length} seleccionados</span>
                  <Link to={`/metadata/shorts/${projectId}`}
                    className="text-xs text-accent hover:text-accent-light transition-colors ml-auto flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> Metadata
                  </Link>
                </div>

                {/* Card grid */}
                <div className="space-y-3 max-h-[600px] overflow-y-auto pr-1">
                  {suggestions.map((seg) => {
                    const isSelected = selected.has(seg.index)
                    const isExpanded = expanded.has(seg.index)
                    const isLong = seg.text_preview.length > 150
                    const isAi = seg.reason.startsWith("ai:")
                    const aiCategory = isAi ? (seg.reason.split("|")[0].replace("ai:", "")) : null

                    return (
                      <div
                        key={seg.index}
                        className={`rounded-lg border transition-all ${
                          isSelected ? "border-accent bg-accent/[0.04]" : "border-border hover:border-accent/30"
                        } ${status === "rendering" ? "pointer-events-none opacity-60" : ""}`}
                      >
                        {/* Card header: score + timing + badges */}
                        <div className="flex items-start gap-3 p-3 pb-2">
                          <input type="checkbox" checked={isSelected}
                            onChange={() => toggleSelect(seg.index)}
                            disabled={status === "rendering"}
                            className="mt-1 w-4 h-4 rounded border-border text-accent focus:ring-accent shrink-0" />

                          {/* Score circle */}
                          <div className={`shrink-0 w-10 h-10 rounded-full border flex items-center justify-center ${scoreBg(seg.score)}`}>
                            <span className={`text-sm font-bold font-mono ${scoreColor(seg.score)}`}>
                              {seg.score.toFixed(1)}
                            </span>
                          </div>

                          <div className="flex-1 min-w-0">
                            {/* Top row: time + badges */}
                            <div className="flex items-center gap-1.5 flex-wrap mb-1">
                              <span className="text-xs font-mono text-accent font-medium">
                                {formatTime(seg.start_sec)} → {formatTime(seg.end_sec)}
                              </span>
                              <span className="text-xs font-mono text-gray-600">{seg.duration.toFixed(0)}s</span>

                              {isAi ? (
                                <span className="text-[11px] px-2 py-0.5 rounded-full border font-medium bg-teal-500/15 text-teal-400 border-teal-500/20">
                                  {aiCategory || "General"}
                                </span>
                              ) : (
                                <span className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${categoryColors[seg.reason] || "bg-gray-800 text-gray-300 border-border"}`}>
                                  {seg.reason}
                                </span>
                              )}

                              {isAi && seg.ai_hook && (
                                <span className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${hookColor(seg.ai_hook)}`}>
                                  Hook: {seg.ai_hook}
                                </span>
                              )}
                              {isAi && seg.ai_viral_potential && (
                                <span className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${viralColor(seg.ai_viral_potential)}`}>
                                  Viral: {seg.ai_viral_potential}
                                </span>
                              )}
                            </div>

                            {/* Reason + metadata button */}
                            <div className="flex items-center gap-2">
                              {isAi && (
                                <span className="text-[11px] text-gray-500 italic truncate">
                                  {seg.reason.split("|").slice(1).join("|") || ""}
                                </span>
                              )}
                              <button onClick={(e) => { e.preventDefault(); handleGenerateShortMetadata(seg.index, seg.text_preview) }}
                                disabled={metadataLoading === seg.index}
                                className="text-[11px] px-2 py-0.5 rounded-full border border-border text-gray-500 hover:text-accent hover:border-accent/30 transition-colors flex items-center gap-1 ml-auto shrink-0">
                                {metadataLoading === seg.index ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                  <Sparkles className="w-3 h-3" />
                                )}
                                {metadataLoading === seg.index ? "..." : existingMetadata.has(String(seg.index)) ? "Meta ✓" : "Meta"}
                              </button>
                            </div>
                          </div>
                        </div>

                        {/* Text preview */}
                        <div className="px-3 pb-3">
                          <div className="ml-[3.25rem]">
                            <p className={`text-sm text-gray-400 font-body cursor-pointer ${
                              isExpanded || !isLong ? "" : "line-clamp-2"
                            }`} onClick={() => toggleExpanded(seg.index)}>
                              {seg.text_preview}
                            </p>
                            {isLong && (
                              <span onClick={() => toggleExpanded(seg.index)}
                                className="text-xs text-accent hover:text-accent-light mt-1 flex items-center gap-1 cursor-pointer">
                                {isExpanded ? <>Show less <ChevronUp className="w-3 h-3" /></> : <>Show more <ChevronDown className="w-3 h-3" /></>}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </>
            )}

            {status === "failed" && suggestions.length === 0 && errorMessage && (
              <div className="text-center py-10">
                <AlertCircle className="w-10 h-10 text-red-500/40 mx-auto mb-3" />
                <p className="text-sm text-red-400 font-body mb-2">Análisis falló</p>
                <p className="text-xs text-gray-500 font-mono mb-4">{errorMessage}</p>
                <button className="btn-primary" onClick={() => handleAnalyze(false)}>
                  <Scissors className="w-4 h-4" /> Reintentar
                </button>
              </div>
            )}
          </Card>

          {/* Progress */}
          {(status === "rendering" || status === "done" || status === "failed") && renderResults.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold text-foreground dark:text-white mb-4 font-sans">Progreso</h3>
              <ProgressBar progress={progress} />
              {progressMessage && <p className="text-xs text-gray-500 mt-2 font-mono">{progressMessage}</p>}
              <div className="mt-4 space-y-2">
                {renderResults.map((r) => (
                  <div key={r.index} className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface-hover/50">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-gray-400">#{r.index}</span>
                      {r.filename && <span className="text-xs text-gray-300 truncate max-w-[200px]">{r.filename}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      {r.success ? (
                        <span className="flex items-center gap-1 text-xs text-green-400">
                          <CheckCircle className="w-3.5 h-3.5" /> Hecho
                        </span>
                      ) : !r.success && r.error ? (
                        <span className="flex items-center gap-1 text-xs text-red-400" title={r.error}>
                          <XCircle className="w-3.5 h-3.5" /> Falló
                        </span>
                      ) : (
                        <span className="text-xs text-gray-600">Pendiente</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Settings */}
          <Card>
            <h3 className="text-sm font-semibold text-foreground dark:text-white mb-4 font-sans">Configuración</h3>
            <div className="space-y-4">
              <div>
                <label className="text-sm text-gray-300 block mb-2">Modo de Análisis</label>
                <div className="flex gap-1 bg-surface-hover rounded-lg p-1">
                  {(["ai", "combined", "rules"] as const).map((m) => (
                    <button key={m} onClick={() => setAnalysisMode(m)}
                      disabled={status === "analyzing" || status === "rendering"}
                      className={`flex-1 text-xs py-1.5 px-2 rounded-md font-medium transition-all ${
                        analysisMode === m ? "bg-accent text-black shadow-sm" : "text-gray-400 hover:text-gray-200"
                      }`}>
                      {m === "ai" ? "AI" : m === "combined" ? "AI+Reglas" : "Reglas"}
                    </button>
                  ))}
                </div>
                <p className="text-[11px] text-gray-600 mt-1.5">
                  {analysisMode === "ai" && "IA lee el texto completo y genera segmentos temáticos. Agnóstico."}
                  {analysisMode === "combined" && "Segmentos por reglas + puntuación de IA."}
                  {analysisMode === "rules" && "Solo reglas clásicas (keywords, hooks)."}
                </p>
              </div>

              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm text-gray-300">Subtítulos</span>
                <input type="checkbox" className="w-4 h-4 rounded border-border bg-surface-hover text-accent focus:ring-accent"
                  checked={withSubtitles} onChange={(e) => setWithSubtitles(e.target.checked)}
                  disabled={status === "rendering"} />
              </label>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm text-gray-300">Tamaño fuente</span>
                  <span className="text-xs font-mono text-accent">{fontSize}px</span>
                </div>
                <input type="range" min="36" max="72" value={fontSize}
                  onChange={(e) => setFontSize(parseInt(e.target.value))}
                  disabled={status === "rendering"}
                  className="w-full h-2 bg-surface-hover rounded-lg appearance-none cursor-pointer"
                  style={{ accentColor: "#2dd4bf" }} />
              </div>
            </div>

            <div className="mt-5 pt-4 border-t border-border">
              <button className="btn-primary w-full" onClick={handleRender}
                disabled={selected.size === 0 || status === "rendering"}>
                {status === "rendering" ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Renderizando...</>
                ) : (
                  <><Play className="w-4 h-4" /> Renderizar ({selected.size})</>
                )}
              </button>
              {selected.size === 0 && status === "ready" && (
                <p className="text-xs text-gray-600 text-center mt-2">Selecciona al menos un segmento</p>
              )}
            </div>
          </Card>

          {/* Quick Stats */}
          {suggestions.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold text-white mb-3 font-sans">Resumen</h3>
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Segmentos</span>
                  <span className="text-gray-300 font-mono">{suggestions.length}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Seleccionados</span>
                  <span className="text-accent font-mono">{selected.size}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Duración total</span>
                  <span className="text-gray-300 font-mono">
                    {suggestions.reduce((a, s) => a + s.duration, 0).toFixed(0)}s
                  </span>
                </div>
                {downloads.length > 0 && (
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500">Shorts render</span>
                    <span className="text-green-400 font-mono">{downloads.length}</span>
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* Downloads */}
          <Card>
            <h3 className="text-sm font-semibold text-foreground dark:text-white mb-4 font-sans">Descargas</h3>
            {downloads.length === 0 ? (
              <p className="text-xs text-gray-600 text-center py-6 font-body">
                {status === "done" ? "Sin archivos" : "Los Shorts renderizados aparecerán aquí"}
              </p>
            ) : (
              <>
                {downloads.length > 0 && status === "done" && (
                  <div className="mb-4">
                    <VideoPlayer src={api.shortsDownloadUrl(projectId!, downloads[0].filename)}
                      className="aspect-[9/16] max-h-[400px] mx-auto" />
                  </div>
                )}
                <div className="space-y-2">
                  {downloads.map((f) => (
                    <div key={f.filename} className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface-hover/50">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-gray-300 font-mono truncate">{f.filename}</p>
                        <p className="text-[11px] text-gray-600">{(f.size_bytes / 1024 / 1024).toFixed(1)} MB</p>
                      </div>
                      <a href={api.shortsDownloadUrl(projectId!, f.filename)} download
                        className="text-accent hover:text-accent-light transition-colors p-1">
                        <Download className="w-4 h-4" />
                      </a>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Card>

          {/* Status */}
          <Card>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider font-sans">Estado</span>
              {status === "done" ? (
                <span className="flex items-center gap-1.5 text-xs text-green-400 font-mono">
                  <CheckCircle className="w-3.5 h-3.5" /> Completo
                </span>
              ) : status === "failed" ? (
                <span className="flex items-center gap-1.5 text-xs text-red-400 font-mono">
                  <AlertCircle className="w-3.5 h-3.5" /> Falló
                </span>
              ) : status === "rendering" ? (
                <span className="flex items-center gap-1.5 text-xs text-accent font-mono">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Renderizando
                </span>
              ) : status === "analyzing" ? (
                <span className="flex items-center gap-1.5 text-xs text-accent font-mono">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Analizando
                </span>
              ) : status === "ready" ? (
                <span className="flex items-center gap-1.5 text-xs text-green-400 font-mono">
                  <Zap className="w-3.5 h-3.5" /> Listo
                </span>
              ) : (
                <span className="text-xs text-gray-500 font-mono">Inactivo</span>
              )}
            </div>
          </Card>
        </div>
      </div>

      {showScriptSelector && projectId && (
        <ScriptSelector projectId={projectId} onSelect={handleScriptSelect} onClose={() => setShowScriptSelector(false)} />
      )}
    </div>
  )
}