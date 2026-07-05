import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useParams, Link } from "react-router-dom"
import {
  Play, Square, CheckCircle, XCircle, Loader2, Image as ImageIcon, Mic,
  Video, FileText, ImageDown, Sparkles, AlertTriangle,
  RefreshCw, Users, Camera, Activity,
} from "lucide-react"
import Card from "../components/Card"
import ProgressBar from "../components/ProgressBar"
import Modal from "../components/Modal"
import EmptyState from "../components/EmptyState"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type {
  ProjectMetadata, Fragment, ImageInfo, KpiSnapshot, ReadinessCheck, LogEntry,
} from "../types"

// ─── Stage model (preserved from previous impl) ───────────

type StageKey = "prompts" | "generate" | "transcribe" | "render" | "thumbnail"
type StageStatus = "idle" | "running" | "completed" | "failed"

interface StageState {
  status: StageStatus
  progress: number
  message: string
}

interface WorkflowState {
  status: "idle" | "running" | "completed" | "failed" | "cancelled"
  currentStage: StageKey | null
  stages: Record<StageKey, StageState>
  error: string | null
}

const STAGE_CONFIG: Record<StageKey, { label: string; icon: typeof ImageIcon; color: string; description: string }> = {
  prompts: { label: "Script y Prompts", icon: Sparkles, color: "text-pink-400", description: "Genera prompts de imagen desde el guion fragmentado" },
  generate: { label: "Generación de Imágenes", icon: ImageIcon, color: "text-purple-400", description: "Crea escenas con las cuentas de Flow conectadas" },
  transcribe: { label: "Transcripción", icon: Mic, color: "text-blue-400", description: "Whisper genera timestamps por palabra" },
  render: { label: "Render", icon: Video, color: "text-green-400", description: "Ensambla el video con Ken Burns sincronizado al audio" },
  thumbnail: { label: "Thumbnail", icon: ImageDown, color: "text-yellow-400", description: "Thumbnail de YouTube con análisis Gemini + fondo IA" },
}

const LOG_RING_MAX = 50

// ─── Data layer (Tasks 1.2 / 1.3 / 1.4) ───────────────────

const SOURCE_KEYS = [
  "project", "fragments", "images", "transcription", "renderState", "references", "accounts",
] as const
type SourceKey = (typeof SOURCE_KEYS)[number]
type SourceResults = Record<SourceKey, unknown>

async function fetchControlRoomData(projectId: string): Promise<{ results: Partial<SourceResults>; errors: Partial<Record<SourceKey, Error>> }> {
  const calls: Array<[SourceKey, Promise<unknown>]> = [
    ["project", api.getProject(projectId)],
    ["fragments", api.listFragments(projectId).then((r) => r.fragments)],
    ["images", api.listImages(projectId).then((r) => r.images)],
    ["transcription", api.getTranscription(projectId)],
    ["renderState", api.getRenderStatus(projectId)],
    ["references", api.listReferences(projectId).then((r) => r.references)],
    ["accounts", api.listAccounts().then((r) => r.accounts)],
  ]
  const settled = await Promise.allSettled(calls.map(([, p]) => p))
  const results: Partial<SourceResults> = {}
  const errors: Partial<Record<SourceKey, Error>> = {}
  settled.forEach((res, i) => {
    const key = calls[i][0]
    if (res.status === "fulfilled") results[key] = res.value
    else errors[key] = res.reason instanceof Error ? res.reason : new Error(String(res.reason))
  })
  return { results, errors }
}

function computeKpis(
  project: ProjectMetadata | undefined,
  fragments: Fragment[] | undefined,
  images: ImageInfo[] | undefined,
  transcription: { has_transcription?: boolean; word_count?: number } | undefined,
  renderState: { has_render?: boolean; output_path?: string } | undefined,
): KpiSnapshot {
  const total = project?.stats?.prompts_total ?? 0
  const withPrompt = fragments ? fragments.filter((f) => (f.image_prompt || "").trim().length > 0).length : 0
  const generated = images ? images.filter((i) => i.status === "done").length : 0
  const failed = images ? images.filter((i) => i.status === "failed").length : 0
  return {
    fragments: { total, withPrompt },
    images: { generated, total, failed },
    audio: { ready: !!transcription?.has_transcription, words: transcription?.word_count },
    output: { hasVideo: !!renderState?.has_render, path: renderState?.output_path },
  }
}

function computeReadiness(
  fragments: Fragment[] | undefined,
  images: ImageInfo[] | undefined,
  references: Array<{ name: string }> | undefined,
  projectId: string | undefined,
): ReadinessCheck[] {
  const all = fragments?.length ? fragments : []
  const missing = all.filter((f) => (f.image_prompt || "").trim().length === 0).length
  const failedCount = images ? images.filter((i) => i.status === "failed").length : 0
  const refCount = references?.length ?? 0

  return [
    {
      id: "prompts",
      label: "Prompts completos",
      description:
        missing === 0
          ? `${all.length} fragmentos listos`
          : `${missing} de ${all.length} fragmentos sin prompt`,
      status: all.length === 0 ? "warn" : missing === 0 ? "ok" : "warn",
      action: missing > 0 && projectId ? { label: "Ir al Editor", to: `/editor/${projectId}` } : undefined,
    },
    {
      id: "failed-images",
      label: "Imágenes fallidas",
      description: failedCount === 0 ? "0 imágenes fallidas" : `${failedCount} imagen(es) fallida(s)`,
      status: failedCount === 0 ? "ok" : "warn",
      action: failedCount > 0 && projectId ? { label: "Retry", to: `/images/${projectId}` } : undefined,
    },
    {
      id: "reference",
      label: "Referencia visual cargada",
      description: refCount > 0 ? `${refCount} referencia(s) en personaje/` : "No hay referencia de personaje",
      status: refCount > 0 ? "ok" : "warn",
      action: refCount === 0 && projectId ? { label: "Subir referencia", to: `/images/${projectId}` } : undefined,
    },
  ]
}

function pushLog(ref: { current: LogEntry[] }, entry: LogEntry) {
  const next = [entry, ...ref.current]
  ref.current = next.length > LOG_RING_MAX ? next.slice(0, LOG_RING_MAX) : next
}

// ─── Component ────────────────────────────────────────────

export default function Workflow() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [workflow, setWorkflow] = useState<WorkflowState>({
    status: "idle",
    currentStage: null,
    stages: {
      prompts: { status: "idle", progress: 0, message: "" },
      generate: { status: "idle", progress: 0, message: "" },
      transcribe: { status: "idle", progress: 0, message: "" },
      render: { status: "idle", progress: 0, message: "" },
      thumbnail: { status: "idle", progress: 0, message: "" },
    },
    error: null,
  })

  // Control room data
  const [project, setProject] = useState<ProjectMetadata | null>(null)
  const [fragments, setFragments] = useState<Fragment[]>([])
  const [images, setImages] = useState<ImageInfo[]>([])
  const [transcription, setTranscription] = useState<{ has_transcription?: boolean; word_count?: number; segment_count?: number } | null>(null)
  const [renderState, setRenderState] = useState<{ has_render?: boolean; output_path?: string } | null>(null)
  const [references, setReferences] = useState<Array<{ name: string; url: string; size_kb: number }>>([])
  const [accounts, setAccounts] = useState<Array<{ hash: string; email: string; connected: boolean }>>([])
  const [errors, setErrors] = useState<Partial<Record<SourceKey, Error>>>({})
  const [initialLoading, setInitialLoading] = useState(true)

  const [showCancelModal, setShowCancelModal] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [stageTimings, setStageTimings] = useState<Record<string, any>>({})
  const [generateThumbnail, setGenerateThumbnail] = useState(false)
  const [thumbnailMode, setThumbnailMode] = useState<"single" | "ab_testing">("single")

  // Live run log (ring buffer)
  const logRef = useRef<LogEntry[]>([])
  const [, forceLogRender] = useState(0)

  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  // ── Parallel fetch on mount + on workflow_complete (Tasks 1.2, 5.2) ──
  const refreshControlRoom = useCallback(async () => {
    if (!projectId) return
    const { results, errors: errs } = await fetchControlRoomData(projectId)
    if (results.project) setProject(results.project as ProjectMetadata)
    if (results.fragments) setFragments(results.fragments as Fragment[])
    if (results.images) setImages(results.images as ImageInfo[])
    if (results.transcription) setTranscription(results.transcription as any)
    if (results.renderState) setRenderState(results.renderState as any)
    if (results.references) setReferences(results.references as any)
    if (results.accounts) setAccounts(results.accounts as any)
    setErrors(errs)
  }, [projectId])

  useEffect(() => {
    refreshControlRoom().finally(() => setInitialLoading(false))
  }, [refreshControlRoom])

  // ── Load existing workflow status (preserved) ──
  useEffect(() => {
    if (!projectId) return
    api.getWorkflowStatus(projectId).then((res) => {
      setWorkflow({
        status: res.status as WorkflowState["status"],
        currentStage: res.current_stage as StageKey | null,
        stages: {
          prompts: buildStage(res, "prompts"),
          generate: buildStage(res, "generate"),
          transcribe: buildStage(res, "transcribe"),
          render: buildStage(res, "render"),
          thumbnail: buildStage(res, "thumbnail"),
        },
        error: res.error,
      })
      if (res.stage_timings) setStageTimings(res.stage_timings)
    }).catch(() => {})
  }, [projectId])

  // Unmount cleanup (preserve)
  useEffect(() => () => { esRef.current?.close() }, [])

  // Polling fallback while running (Task 5.3)
  useEffect(() => {
    if (workflow.status !== "running") return
    const interval = setInterval(async () => {
      if (!projectId) return
      try {
        const res = await api.getWorkflowStatus(projectId)
        setWorkflow((prev) => ({
          ...prev,
          status: res.status as WorkflowState["status"],
          currentStage: res.current_stage as StageKey | null,
          stages: {
            prompts: { ...prev.stages.prompts, status: (res.stages.prompts?.status || prev.stages.prompts.status) as StageStatus, progress: res.stages.prompts?.progress ?? prev.stages.prompts.progress },
            generate: { ...prev.stages.generate, status: (res.stages.generate?.status || prev.stages.generate.status) as StageStatus, progress: res.stages.generate?.progress ?? prev.stages.generate.progress },
            transcribe: { ...prev.stages.transcribe, status: (res.stages.transcribe?.status || prev.stages.transcribe.status) as StageStatus, progress: res.stages.transcribe?.progress ?? prev.stages.transcribe.progress },
            render: { ...prev.stages.render, status: (res.stages.render?.status || prev.stages.render.status) as StageStatus, progress: res.stages.render?.progress ?? prev.stages.render.progress },
            thumbnail: { ...prev.stages.thumbnail, status: (res.stages.thumbnail?.status || prev.stages.thumbnail.status) as StageStatus, progress: res.stages.thumbnail?.progress ?? prev.stages.thumbnail.progress },
          },
          error: res.error,
        }))
        if (res.stage_timings) setStageTimings(res.stage_timings)
      } catch {}
    }, 2000)
    return () => clearInterval(interval)
  }, [workflow.status, projectId])

  // Live timer (preserve)
  useEffect(() => {
    if (workflow.status !== "running") return
    setElapsed(0)
    const start = Date.now()
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [workflow.status])

  // ── SSE lifecycle (Task 5.3) — preserved + log entries ──
  const connectSSE = () => {
    if (!projectId) return
    esRef.current?.close()
    const es = new EventSource(api.workflowEventsUrl(projectId))
    esRef.current = es

    const addLog = (message: string, level: LogEntry["level"] = "info", stage?: string) => {
      pushLog(logRef, { timestamp: new Date().toISOString(), message, level, stage })
      forceLogRender((n) => n + 1)
    }

    es.addEventListener("workflow_start", () => {
      setWorkflow((prev) => ({ ...prev, status: "running", error: null }))
      addLog("Workflow iniciado", "info")
    })

    es.addEventListener("workflow_stage_start", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, currentStage: stage, stages: { ...prev.stages, [stage]: { ...prev.stages[stage], status: "running", progress: 0 } } }))
      addLog(`Etapa iniciada: ${STAGE_CONFIG[stage]?.label ?? stage}`, "info", stage)
    })

    es.addEventListener("workflow_stage_complete", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, stages: { ...prev.stages, [stage]: { ...prev.stages[stage], status: "completed", progress: 1 } } }))
      addLog(`Etapa completada: ${STAGE_CONFIG[stage]?.label ?? stage}`, "info", stage)
    })

    es.addEventListener("workflow_stage_failed", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, status: "failed", stages: { ...prev.stages, [stage]: { ...prev.stages[stage], status: "failed" } }, error: data.error }))
      addLog(`Etapa fallida: ${STAGE_CONFIG[stage]?.label ?? stage} — ${data.error ?? ""}`, "error", stage)
    })

    es.addEventListener("workflow_progress", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, stages: { ...prev.stages, [stage]: { ...prev.stages[stage], progress: data.progress, message: data.message || "" } } }))
      if (data.message) addLog(data.message, "info", stage)
    })

    es.addEventListener("workflow_complete", () => {
      setWorkflow((prev) => ({ ...prev, status: "completed", currentStage: null }))
      toast("Workflow completed successfully!", "success")
      addLog("Workflow completado ✓", "info")
      // Re-fetch KPI/readiness after completion (Task 5.2)
      refreshControlRoom()
    })

    es.addEventListener("workflow_failed", (e) => {
      const data = JSON.parse(e.data)
      setWorkflow((prev) => ({ ...prev, status: "failed", error: data.error }))
      toast(`Workflow failed: ${data.error}`, "error")
      addLog(`Workflow fallido: ${data.error ?? ""}`, "error")
    })

    es.onerror = () => {
      console.log("[Workflow] SSE connection error (polling fallback active)")
    }
  }

  const handleStart = () => {
    if (!projectId) return
    connectSSE()
    // Preserve existing start payload convention (backend accepts generate_thumbnail / thumbnail_mode even if TS sig omits them)
    const config: Record<string, any> = {}
    const savedConcurrency = sessionStorage.getItem(`images-${projectId}-concurrency`)
    const savedAccounts = sessionStorage.getItem(`images-${projectId}-accounts`)
    const savedModel = sessionStorage.getItem(`images-${projectId}-model`)
    if (savedConcurrency) config.concurrency = Number(savedConcurrency)
    if (savedAccounts) config.accounts = JSON.parse(savedAccounts)
    if (savedModel) config.model = savedModel
    config.generate_thumbnail = generateThumbnail
    config.thumbnail_mode = thumbnailMode
    api.startWorkflow(projectId, config)
      .then(() => setWorkflow((prev) => ({ ...prev, status: "running", error: null })))
      .catch((err: any) => toast(err?.message ?? "Failed to start workflow", "error"))
  }

  const handleCancelConfirm = async () => {
    if (!projectId) return
    try {
      await api.cancelWorkflow(projectId)
      setShowCancelModal(false)
      setWorkflow((prev) => ({ ...prev, status: "cancelled", error: "Cancelled by user" }))
    } catch (err: any) {
      toast(err?.message ?? "Failed to cancel workflow", "error")
    }
  }

  // ── Derived data (memoized) ──
  const kpis = useMemo(
    () => computeKpis(project ?? undefined, fragments, images, transcription ?? undefined, renderState ?? undefined),
    [project, fragments, images, transcription, renderState],
  )
  const readiness = useMemo(
    () => computeReadiness(fragments, images, references, projectId),
    [fragments, images, references, projectId],
  )
  const recentScenes = useMemo(
    () => images.filter((i) => i.status === "done" && i.url).slice(-6).reverse(),
    [images],
  )

  if (!projectId) {
    return (
      <EmptyState
        icon={<Play />}
        title="No project selected"
        description="Select a project from the Dashboard to run the workflow"
      />
    )
  }

  const isRunning = workflow.status === "running"
  const isCompleted = workflow.status === "completed"
  const isFailed = workflow.status === "failed" || workflow.status === "cancelled"
  const isIdle = workflow.status === "idle"
  const connectedAccounts = accounts.filter((a) => a.connected).length

  return (
    <div className="space-y-6 animate-slide-down">
      {/* ── Topbar (Task 2.1) ── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          {project && (
            <p className="text-[11px] uppercase tracking-wide text-gray-600 font-mono mb-1 truncate">
              {project.title || project.name}
            </p>
          )}
          <h1 className="text-2xl font-bold text-white">Workflow Control Room</h1>
          <p className="mt-1 text-sm text-gray-500 font-body">
            Pipeline completo: prompts → imágenes → transcripción → render → thumbnail
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {isRunning ? (
            <button className="btn-secondary !bg-red-600/10 !border-red-500/30 hover:!bg-red-600/20 text-red-400" onClick={() => setShowCancelModal(true)}>
              <Square className="w-4 h-4" />
              Cancel
            </button>
          ) : (
            <button className="btn-primary" onClick={handleStart} disabled={isRunning}>
              <Play className="w-4 h-4" />
              {isCompleted ? "Run Again" : isFailed ? "Run Ready Stages" : "Run Ready Stages"}
            </button>
          )}
        </div>
      </div>

      {/* ── Command banner (Task 2.2) ── */}
      <Card className="bg-gradient-to-br from-surface-card to-accent/5">
        <div className="flex flex-wrap items-center gap-3 justify-between">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Status pill */}
            {isRunning && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-accent/15 text-accent">
                <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" /> Running
              </span>
            )}
            {isIdle && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-hover text-gray-400">
                <span className="w-1.5 h-1.5 rounded-full bg-gray-500" /> Idle
              </span>
            )}
            {isCompleted && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-400">
                <CheckCircle className="w-3 h-3" /> Completed
              </span>
            )}
            {isFailed && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-500/15 text-red-400">
                <XCircle className="w-3 h-3" /> {workflow.status === "cancelled" ? "Cancelled" : "Failed"}
              </span>
            )}
            {/* Accounts connected */}
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-hover text-gray-400">
              <Users className="w-3 h-3" /> {connectedAccounts} cuenta{connectedAccounts !== 1 ? "s" : ""}
            </span>
            {/* Elapsed */}
            {isRunning && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono text-gray-400">
                {Math.floor(elapsed / 60)}m {elapsed % 60}s
              </span>
            )}
            {workflow.currentStage && isRunning && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-accent/10 text-accent">
                {STAGE_CONFIG[workflow.currentStage]?.label ?? workflow.currentStage}
              </span>
            )}
          </div>
          {/* Thumbnail toggle (preserved) */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <span className="text-xs text-gray-400">Thumbnail</span>
              <input
                type="checkbox"
                className="sr-only peer"
                checked={generateThumbnail}
                onChange={(e) => setGenerateThumbnail(e.target.checked)}
              />
              <div className="w-10 h-6 bg-surface-hover rounded-full peer peer-checked:bg-accent peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-0.5 after:start-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all relative" />
            </label>
            {generateThumbnail && (
              <div className="flex gap-1 bg-surface-hover rounded-lg p-0.5">
                <button
                  className={`px-2.5 py-1 text-xs rounded-md transition-all ${thumbnailMode === "single" ? "bg-accent/20 text-accent border border-accent/30" : "text-gray-500 hover:text-white"}`}
                  onClick={() => setThumbnailMode("single")}
                >
                  Single
                </button>
                <button
                  className={`px-2.5 py-1 text-xs rounded-md transition-all ${thumbnailMode === "ab_testing" ? "bg-accent/20 text-accent border border-accent/30" : "text-gray-500 hover:text-white"}`}
                  onClick={() => setThumbnailMode("ab_testing")}
                >
                  A/B
                </button>
              </div>
            )}
          </div>
        </div>
        {isFailed && workflow.error && (
          <p className="mt-3 text-xs text-red-400/80 border-t border-red-500/20 pt-3">
            {workflow.error}
          </p>
        )}
      </Card>

      {/* ── 4 KPI cards (Task 2.3) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          icon={<FileText className="w-4 h-4" />}
          label="Fragments"
          value={String(kpis.fragments.total)}
          subtitle={errors.fragments ? "—" : `${kpis.fragments.withPrompt} con prompt`}
          error={!!errors.project}
          accent="text-accent"
        />
        <KpiCard
          icon={<ImageIcon className="w-4 h-4" />}
          label="Imágenes"
          value={errors.images ? "—" : `${kpis.images.generated}/${kpis.images.total}`}
          subtitle={errors.images ? "Unavailable" : `${kpis.images.total - kpis.images.generated} pendientes${kpis.images.failed ? `, ${kpis.images.failed} fallidas` : ""}`}
          error={!!errors.images}
          accent="text-purple-400"
        />
        <KpiCard
          icon={<Mic className="w-4 h-4" />}
          label="Audio"
          value={errors.transcription ? "—" : kpis.audio.ready ? "Ready" : "Pending"}
          subtitle={errors.transcription ? "Unavailable" : kpis.audio.ready ? `${kpis.audio.words ?? 0} palabras` : "Sin transcripción"}
          error={!!errors.transcription}
          accent="text-blue-400"
        />
        <KpiCard
          icon={<Video className="w-4 h-4" />}
          label="Output"
          value={errors.renderState ? "—" : kpis.output.hasVideo ? "1" : "0"}
          subtitle={errors.renderState ? "Unavailable" : kpis.output.hasVideo ? "Render final listo" : "Render final pendiente"}
          error={!!errors.renderState}
          accent="text-green-400"
        />
      </div>

      {/* ── Main 2-column grid (Task 5.1) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Pipeline stages */}
        <Card>
          <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border">
            <Activity className="w-4 h-4 text-accent" />
            <h2 className="text-sm font-semibold text-white font-sans">Pipeline Stages</h2>
          </div>
          <div className="space-y-3">
            {(Object.keys(STAGE_CONFIG) as StageKey[]).map((stageKey, index) => {
              const config = STAGE_CONFIG[stageKey]
              const stage = workflow.stages[stageKey]
              const Icon = config.icon
              const isCurrentStage = workflow.currentStage === stageKey
              const isThumbnailOptional = stageKey === "thumbnail" && !generateThumbnail
              return (
                <div
                  key={stageKey}
                  className={`flex items-start gap-3 p-3 rounded-lg border transition-all ${
                    isCurrentStage
                      ? "ring-1 ring-accent/50 border-accent/30 bg-accent/5"
                      : stage.status === "completed"
                        ? "border-green-500/15 bg-green-500/[0.03]"
                        : stage.status === "failed"
                          ? "border-red-500/20 bg-red-500/[0.03]"
                          : "border-border"
                  } ${isThumbnailOptional ? "opacity-60" : ""}`}
                >
                  {/* Icon box */}
                  <div className={`p-2.5 rounded-lg shrink-0 ${
                    stage.status === "completed" ? "bg-green-500/10" :
                    stage.status === "running" ? "bg-accent/10" :
                    stage.status === "failed" ? "bg-red-500/10" :
                    "bg-surface-hover"
                  }`}>
                    {stage.status === "completed" ? (
                      <CheckCircle className="w-5 h-5 text-green-400" />
                    ) : stage.status === "failed" ? (
                      <XCircle className="w-5 h-5 text-red-400" />
                    ) : stage.status === "running" ? (
                      <Loader2 className="w-5 h-5 text-accent animate-spin" />
                    ) : (
                      <Icon className={`w-5 h-5 ${config.color}`} />
                    )}
                  </div>
                  {/* Middle: title + desc + progress */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[10px] text-gray-600 font-mono">{index + 1}</span>
                      <h3 className="text-sm font-semibold text-white font-sans truncate">{config.label}</h3>
                    </div>
                    <p className="text-xs text-gray-500 leading-snug">
                      {isThumbnailOptional ? "Optional — enable en settings" : config.description}
                    </p>
                    {stage.status === "running" && (
                      <div className="mt-2">
                        <ProgressBar progress={stage.progress * 100} />
                        {stage.message && <p className="text-[11px] text-gray-500 mt-1.5 truncate">{stage.message}</p>}
                      </div>
                    )}
                    {stage.status === "completed" && stageTimings[stageKey]?.duration_s && (
                      <p className="text-[11px] text-green-400/80 mt-1">
                        Completado · {Math.round(stageTimings[stageKey].duration_s / 60)}m {Math.round(stageTimings[stageKey].duration_s % 60)}s
                      </p>
                    )}
                    {stage.status === "failed" && (
                      <p className="text-[11px] text-red-400/80 mt-1 truncate" title={workflow.error ?? ""}>
                        {workflow.error ?? "Failed"}
                      </p>
                    )}
                  </div>
                  {/* Right: badge */}
                  <div className="shrink-0">
                    {stage.status === "completed" && (
                      <span className="px-2 py-1 text-xs font-medium text-green-400 bg-green-500/10 rounded">Done</span>
                    )}
                    {stage.status === "running" && (
                      <span className="px-2 py-1 text-xs font-medium text-accent bg-accent/10 rounded">{Math.round(stage.progress * 100)}%</span>
                    )}
                    {stage.status === "failed" && (
                      <span className="px-2 py-1 text-xs font-medium text-red-400 bg-red-500/10 rounded">Failed</span>
                    )}
                    {stage.status === "idle" && (
                      <span className="px-2 py-1 text-xs font-medium text-gray-600 bg-surface-hover rounded">Pending</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          {/* How it works (only when idle) */}
          {isIdle && (
            <div className="mt-4 pt-4 border-t border-border">
              <h3 className="text-sm font-semibold text-white mb-2 font-sans">How it works</h3>
              <ol className="space-y-1.5 text-xs text-gray-400">
                <li className="flex gap-2"><span className="text-accent font-mono">1.</span><span><strong className="text-gray-300">Prompts:</strong> Crea prompts desde el guion con Gemini/OpenRouter</span></li>
                <li className="flex gap-2"><span className="text-accent font-mono">2.</span><span><strong className="text-gray-300">Imágenes:</strong> Genera escenas con la Forge bridge vía cuentas de Flow</span></li>
                <li className="flex gap-2"><span className="text-accent font-mono">3.</span><span><strong className="text-gray-300">Transcribe:</strong> Whisper con timestamps por palabra</span></li>
                <li className="flex gap-2"><span className="text-accent font-mono">4.</span><span><strong className="text-gray-300">Render:</strong> Ken Burns sincronizado al audio</span></li>
                <li className="flex gap-2"><span className="text-accent font-mono">5.</span><span><strong className="text-gray-300">Thumbnail:</strong> (Opcional) Gemini análisis + background IA</span></li>
              </ol>
            </div>
          )}
        </Card>

        {/* Right: side stack */}
        <div className="space-y-6">
          {/* Readiness (Task 3.1) */}
          <Card>
            <div className="flex items-center gap-2 mb-3 pb-2 border-b border-border">
              <CheckCircle className="w-4 h-4 text-accent" />
              <h2 className="text-sm font-semibold text-white font-sans">Readiness</h2>
            </div>
            <div className="space-y-2.5">
              {readiness.map((check) => {
                const ok = check.status === "ok"
                return (
                  <div key={check.id} className="flex items-start gap-3">
                    {ok ? (
                      <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm text-white font-sans">{check.label}</p>
                        {ok ? (
                          <span className="px-1.5 py-0.5 text-[10px] font-medium text-green-400 bg-green-500/10 rounded">OK</span>
                        ) : check.action?.to ? (
                          <Link to={check.action.to} className="px-1.5 py-0.5 text-[10px] font-medium text-amber-400 bg-amber-500/10 rounded hover:bg-amber-500/20 transition-colors">
                            {check.action.label}
                          </Link>
                        ) : (
                          <span className="px-1.5 py-0.5 text-[10px] font-medium text-amber-400 bg-amber-500/10 rounded">Fix</span>
                        )}
                      </div>
                      <p className="text-[11px] text-gray-500 mt-0.5">{check.description}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>

          {/* Scene preview (Task 3.2) */}
          <Card>
            <div className="flex items-center justify-between mb-3 pb-2 border-b border-border">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4 text-accent" />
                <h2 className="text-sm font-semibold text-white font-sans">Scene Preview</h2>
              </div>
              {projectId && recentScenes.length > 0 && (
                <Link to={`/images/${projectId}`} className="text-[11px] text-gray-500 hover:text-accent flex items-center gap-1">
                  Ver todas <RefreshCw className="w-3 h-3" />
                </Link>
              )}
            </div>
            {initialLoading ? (
              <div className="grid grid-cols-3 gap-2 animate-pulse">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="aspect-video bg-surface-hover rounded-lg" />
                ))}
              </div>
            ) : recentScenes.length === 0 ? (
              <EmptyState
                icon={<ImageIcon />}
                title="No scenes generated yet"
                description="Genera imágenes para ver previews aquí"
              />
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {recentScenes.map((img) => (
                  <Link
                    key={img.fragment_id}
                    to={`/images/${projectId}`}
                    className="aspect-video rounded-lg overflow-hidden border border-border bg-surface-elevated group hover:border-accent/40 transition-colors"
                  >
                    <img
                      src={img.url}
                      alt={`Scene ${img.fragment_id}`}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      loading="lazy"
                    />
                  </Link>
                ))}
              </div>
            )}
          </Card>

          {/* Live run log (Task 3.3) */}
          <Card>
            <div className="flex items-center justify-between mb-3 pb-2 border-b border-border">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-accent" />
                <h2 className="text-sm font-semibold text-white font-sans">Live Run Log</h2>
              </div>
              {isRunning && (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-accent/15 text-accent">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" /> Live
                </span>
              )}
            </div>
            {logRef.current.length === 0 ? (
              <p className="text-xs text-gray-600 text-center py-6">
                El log se actualiza en vivo al ejecutar el workflow. <span className="block mt-1 text-gray-700">(Live log se resetea al recargar)</span>
              </p>
            ) : (
              <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
                {logRef.current.map((entry, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs font-mono">
                    <span className="text-gray-700 shrink-0">
                      {new Date(entry.timestamp).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                    <span className={`shrink-0 ${entry.level === "error" ? "text-red-400" : entry.level === "warn" ? "text-amber-400" : "text-gray-400"}`}>
                      ›
                    </span>
                    <span className={`min-w-0 break-words ${entry.level === "error" ? "text-red-300" : entry.level === "warn" ? "text-amber-300" : "text-gray-300"}`}>
                      {entry.message}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

      <Modal open={showCancelModal} onClose={() => setShowCancelModal(false)} title="Cancel Workflow">
        <p className="text-sm text-gray-300 mb-6">¿Seguro que quieres cancelar el workflow actual? No se puede deshacer.</p>
        <div className="flex justify-end gap-3">
          <button className="btn-secondary" onClick={() => setShowCancelModal(false)}>Keep Running</button>
          <button className="btn-primary !bg-red-600 !border-red-600 hover:!bg-red-700" onClick={handleCancelConfirm}>Yes, Cancel</button>
        </div>
      </Modal>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────

function buildStage(res: { stages: Record<string, { status: string; progress: number } | undefined> }, key: StageKey): StageState {
  return {
    status: (res.stages[key]?.status || "idle") as StageStatus,
    progress: res.stages[key]?.progress || 0,
    message: "",
  }
}

interface KpiCardProps {
  icon: ReactNode
  label: string
  value: string
  subtitle: string
  error?: boolean
  accent?: string
}

function KpiCard({ icon, label, value, subtitle, error, accent = "text-accent" }: KpiCardProps) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <span className={accent}>{icon}</span>
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</span>
      </div>
      {error ? (
        <EmptyState icon={<AlertTriangle className="w-6 h-6" />} title="Unavailable" description="Failed to load" />
      ) : (
        <>
          <p className="text-2xl font-bold text-white font-sans">{value}</p>
          <p className="text-xs text-gray-500 mt-1 truncate">{subtitle}</p>
        </>
      )}
    </Card>
  )
}