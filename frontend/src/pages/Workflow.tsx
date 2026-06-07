import { useCallback, useEffect, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import { Play, Square, CheckCircle, XCircle, Loader2, Image, Mic, Video, Folder, FileText, Clock, AlertTriangle } from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import ProgressBar from "../components/ProgressBar"
import Modal from "../components/Modal"
import EmptyState from "../components/EmptyState"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type { ProjectMetadata } from "../types"

type StageKey = "generate" | "transcribe" | "render"
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

const STAGE_CONFIG: Record<StageKey, { label: string; icon: typeof Image; color: string }> = {
  generate: { label: "Generate Images", icon: Image, color: "text-purple-400" },
  transcribe: { label: "Transcribe Audio", icon: Mic, color: "text-blue-400" },
  render: { label: "Render Video", icon: Video, color: "text-green-400" },
}

export default function Workflow() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [workflow, setWorkflow] = useState<WorkflowState>({
    status: "idle",
    currentStage: null,
    stages: {
      generate: { status: "idle", progress: 0, message: "" },
      transcribe: { status: "idle", progress: 0, message: "" },
      render: { status: "idle", progress: 0, message: "" },
    },
    error: null,
  })

  const [project, setProject] = useState<ProjectMetadata | null>(null)
  const [loading, setLoading] = useState(true)
  const [showCancelModal, setShowCancelModal] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [stageTimings, setStageTimings] = useState<Record<string, any>>({})

  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getWorkflowStatus(projectId).then((res) => {
      setWorkflow({
        status: res.status as WorkflowState["status"],
        currentStage: res.current_stage as StageKey | null,
        stages: {
          generate: {
            status: (res.stages.generate?.status || "idle") as StageStatus,
            progress: res.stages.generate?.progress || 0,
            message: "",
          },
          transcribe: {
            status: (res.stages.transcribe?.status || "idle") as StageStatus,
            progress: res.stages.transcribe?.progress || 0,
            message: "",
          },
          render: {
            status: (res.stages.render?.status || "idle") as StageStatus,
            progress: res.stages.render?.progress || 0,
            message: "",
          },
        },
        error: res.error,
      })
    }).catch(() => {})
  }, [projectId])

  const loadProject = useCallback(async () => {
    if (!projectId) return
    try {
      const res = await api.getProject(projectId)
      setProject(res)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    loadProject()
  }, [loadProject])

  useEffect(() => {
    return () => { esRef.current?.close() }
  }, [])

  // Polling fallback when workflow is running (SSE might miss events)
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
            generate: { ...prev.stages.generate, status: (res.stages.generate?.status || prev.stages.generate.status) as StageStatus, progress: res.stages.generate?.progress ?? prev.stages.generate.progress },
            transcribe: { ...prev.stages.transcribe, status: (res.stages.transcribe?.status || prev.stages.transcribe.status) as StageStatus, progress: res.stages.transcribe?.progress ?? prev.stages.transcribe.progress },
            render: { ...prev.stages.render, status: (res.stages.render?.status || prev.stages.render.status) as StageStatus, progress: res.stages.render?.progress ?? prev.stages.render.progress },
          },
          error: res.error,
        }))
        if (res.stage_timings) setStageTimings(res.stage_timings)
      } catch {}
    }, 2000)
    return () => clearInterval(interval)
  }, [workflow.status, projectId])

  // Live timer — counts up every second while running
  useEffect(() => {
    if (workflow.status !== "running") return
    setElapsed(0)
    const start = Date.now()
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [workflow.status])

  const connectSSE = () => {
    if (!projectId) return
    esRef.current?.close()
    const es = new EventSource(api.workflowEventsUrl(projectId))
    esRef.current = es

    es.addEventListener("workflow_start", () => {
      setWorkflow((prev) => ({ ...prev, status: "running", error: null }))
    })

    es.addEventListener("workflow_stage_start", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, currentStage: stage, stages: { ...prev.stages, [stage]: { ...prev.stages[stage], status: "running", progress: 0 } } }))
    })

    es.addEventListener("workflow_stage_complete", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, stages: { ...prev.stages, [stage]: { ...prev.stages[stage], status: "completed", progress: 1 } } }))
    })

    es.addEventListener("workflow_stage_failed", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, status: "failed", stages: { ...prev.stages, [stage]: { ...prev.stages[stage], status: "failed" } }, error: data.error }))
    })

    es.addEventListener("workflow_progress", (e) => {
      const data = JSON.parse(e.data)
      const stage = data.stage as StageKey
      setWorkflow((prev) => ({ ...prev, stages: { ...prev.stages, [stage]: { ...prev.stages[stage], progress: data.progress, message: data.message || "" } } }))
    })

    es.addEventListener("workflow_complete", () => {
      setWorkflow((prev) => ({ ...prev, status: "completed", currentStage: null }))
      toast("Workflow completed successfully!", "success")
    })

    es.addEventListener("workflow_failed", (e) => {
      const data = JSON.parse(e.data)
      setWorkflow((prev) => ({ ...prev, status: "failed", error: data.error }))
      toast(`Workflow failed: ${data.error}`, "error")
    })

    es.onerror = () => {
      // SSE error is expected when connection drops; polling will catch up
      console.log("[Workflow] SSE connection error (polling fallback active)")
    }
  }

  const handleStart = async () => {
    if (!projectId) return
    connectSSE()
    try {
      const savedConcurrency = projectId ? sessionStorage.getItem(`images-${projectId}-concurrency`) : null
      const savedAccounts = projectId ? sessionStorage.getItem(`images-${projectId}-accounts`) : null
      const config: Record<string, any> = {}
      if (savedConcurrency) config.concurrency = Number(savedConcurrency)
      if (savedAccounts) config.accounts = JSON.parse(savedAccounts)
      await api.startWorkflow(projectId, config)
      setWorkflow((prev) => ({ ...prev, status: "running", error: null }))
    } catch (err: any) {
      toast(err?.message ?? "Failed to start workflow", "error")
    }
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

  return (
    <div>
      <PageHeader
        title="Workflow Orchestrator"
        description="Run the complete pipeline: generate images, transcribe audio, render video"
        actions={
          isRunning ? (
            <button className="btn-secondary" onClick={() => setShowCancelModal(true)}>
              <Square className="w-4 h-4" />
              Cancel
            </button>
          ) : (
            <button
              className="btn-primary"
              onClick={handleStart}
              disabled={isRunning}
            >
              <Play className="w-4 h-4" />
              {isCompleted ? "Run Again" : "Start Workflow"}
            </button>
          )
        }
      />

      {/* Project Summary */}
      {project && !loading && (
        <Card className="mb-6">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <Folder className="w-5 h-5 text-accent" />
              <div>
                <h2 className="text-base font-semibold text-white font-sans">{project.title || project.name}</h2>
                <p className="text-xs text-gray-500 font-mono mt-0.5">{projectId}</p>
              </div>
            </div>
            <span className={`px-2 py-1 text-xs font-medium rounded ${
              project.status === "completed" ? "text-green-400 bg-green-500/10" :
              project.status === "failed" ? "text-red-400 bg-red-500/10" :
              project.status === "generating" ? "text-accent bg-accent/10" :
              "text-gray-500 bg-surface-hover"
            }`}>
              {project.status}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-border">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-gray-600" />
              <div>
                <p className="text-xs text-gray-600">Fragments</p>
                <p className="text-sm text-white font-medium">{project.stats.prompts_total}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Image className="w-4 h-4 text-gray-600" />
              <div>
                <p className="text-xs text-gray-600">Images</p>
                <p className="text-sm text-white font-medium">{project.stats.images_generated} / {project.stats.prompts_total}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-600" />
              <div>
                <p className="text-xs text-gray-600">Created</p>
                <p className="text-sm text-white font-medium">{new Date(project.created).toLocaleDateString()}</p>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Status Banner */}
      {isCompleted && (
        <Card className="mb-6 border-green-500/30 bg-green-500/5">
          <div className="flex items-center gap-3">
            <CheckCircle className="w-5 h-5 text-green-400" />
            <div>
              <p className="text-sm font-medium text-green-400">Workflow Completed</p>
              <p className="text-xs text-gray-500">
                Total time: {Math.floor(elapsed / 60)}m {elapsed % 60}s
              </p>
            </div>
          </div>
        </Card>
      )}

      {isFailed && (
        <Card className={`mb-6 ${workflow.status === "cancelled" ? "border-yellow-500/30 bg-yellow-500/5" : "border-red-500/30 bg-red-500/5"}`}>
          <div className="flex items-center gap-3">
            {workflow.status === "cancelled" ? (
              <AlertTriangle className="w-5 h-5 text-yellow-400" />
            ) : (
              <XCircle className="w-5 h-5 text-red-400" />
            )}
            <div>
              <p className={`text-sm font-medium ${workflow.status === "cancelled" ? "text-yellow-400" : "text-red-400"}`}>
                {workflow.status === "cancelled" ? "Workflow Cancelled" : "Workflow Failed"}
              </p>
              <p className="text-xs text-gray-500">{workflow.error}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Running Banner with Timer */}
      {isRunning && (
        <Card className="mb-6 border-accent/30 bg-accent/5">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-accent animate-spin" />
            <div className="flex-1">
              <p className="text-sm font-medium text-accent">Workflow Running</p>
              <p className="text-xs text-gray-500">
                Elapsed: {Math.floor(elapsed / 60)}m {elapsed % 60}s
                {workflow.currentStage && ` — Stage: ${STAGE_CONFIG[workflow.currentStage as StageKey]?.label || workflow.currentStage}`}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Pipeline Stages */}
      <div className="space-y-4">
        {(Object.keys(STAGE_CONFIG) as StageKey[]).map((stageKey, index) => {
          const config = STAGE_CONFIG[stageKey]
          const stage = workflow.stages[stageKey]
          const Icon = config.icon
          const isCurrentStage = workflow.currentStage === stageKey
          
          return (
            <Card key={stageKey} className={isCurrentStage ? "ring-1 ring-accent/50" : ""}>
              <div className="flex items-start gap-4">
                {/* Stage Icon */}
                <div className={`p-3 rounded-lg ${
                  stage.status === "completed" ? "bg-green-500/10" :
                  stage.status === "running" ? "bg-accent/10" :
                  stage.status === "failed" ? "bg-red-500/10" :
                  "bg-surface-hover"
                }`}>
                  {stage.status === "completed" ? (
                    <CheckCircle className="w-6 h-6 text-green-400" />
                  ) : stage.status === "failed" ? (
                    <XCircle className="w-6 h-6 text-red-400" />
                  ) : stage.status === "running" ? (
                    <Loader2 className="w-6 h-6 text-accent animate-spin" />
                  ) : (
                    <Icon className={`w-6 h-6 ${config.color}`} />
                  )}
                </div>

                {/* Stage Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs text-gray-600 font-mono">Stage {index + 1}</span>
                    <h3 className="text-sm font-semibold text-white font-sans">
                      {config.label}
                    </h3>
                  </div>

                  {stage.status === "running" && (
                    <div className="mt-3">
                      <ProgressBar progress={stage.progress * 100} />
                      {stage.message && (
                        <p className="text-xs text-gray-500 mt-2">{stage.message}</p>
                      )}
                    </div>
                  )}

                  {stage.status === "completed" && (
                    <p className="text-xs text-green-400 mt-1">
                      Completed
                      {stageTimings[stageKey]?.duration_s ? ` — ${Math.round(stageTimings[stageKey].duration_s / 60)}m ${Math.round(stageTimings[stageKey].duration_s % 60)}s` : ""}
                    </p>
                  )}

                  {stage.status === "failed" && (
                    <p className="text-xs text-red-400 mt-1">
                      Failed
                      {stageTimings[stageKey]?.duration_s ? ` (${Math.round(stageTimings[stageKey].duration_s / 60)}m ${Math.round(stageTimings[stageKey].duration_s % 60)}s)` : ""}
                    </p>
                  )}

                  {stage.status === "idle" && (
                    <p className="text-xs text-gray-600 mt-1">Waiting...</p>
                  )}
                </div>

                {/* Stage Status Badge */}
                <div className="shrink-0">
                  {stage.status === "completed" && (
                    <span className="px-2 py-1 text-xs font-medium text-green-400 bg-green-500/10 rounded">
                      Done
                    </span>
                  )}
                  {stage.status === "running" && (
                    <span className="px-2 py-1 text-xs font-medium text-accent bg-accent/10 rounded">
                      {Math.round(stage.progress * 100)}%
                    </span>
                  )}
                  {stage.status === "failed" && (
                    <span className="px-2 py-1 text-xs font-medium text-red-400 bg-red-500/10 rounded">
                      Failed
                    </span>
                  )}
                  {stage.status === "idle" && (
                    <span className="px-2 py-1 text-xs font-medium text-gray-600 bg-surface-hover rounded">
                      Pending
                    </span>
                  )}
                </div>
              </div>
            </Card>
          )
        })}
      </div>

      {/* Info Card */}
      {isIdle && (
        <Card className="mt-6">
          <h3 className="text-sm font-semibold text-white mb-3 font-sans">How it works</h3>
          <ol className="space-y-2 text-sm text-gray-400">
            <li className="flex gap-2">
              <span className="text-accent font-mono">1.</span>
              <span><strong className="text-gray-300">Generate Images:</strong> Creates scene images from your prompts using the Forge bridge</span>
            </li>
            <li className="flex gap-2">
              <span className="text-accent font-mono">2.</span>
              <span><strong className="text-gray-300">Transcribe Audio:</strong> Transcribes your audio file using Whisper with word timestamps</span>
            </li>
            <li className="flex gap-2">
              <span className="text-accent font-mono">3.</span>
              <span><strong className="text-gray-300">Render Video:</strong> Creates the final video with Ken Burns effect, synchronized to audio</span>
            </li>
          </ol>
          <p className="text-xs text-gray-600 mt-4">
            Make sure you have prompts.json and an audio file in the audio/ folder before starting.
          </p>
        </Card>
      )}

      <Modal open={showCancelModal} onClose={() => setShowCancelModal(false)} title="Cancel Workflow">
        <p className="text-sm text-gray-300 mb-6">Are you sure you want to cancel the current workflow? This cannot be undone.</p>
        <div className="flex justify-end gap-3">
          <button className="btn-secondary" onClick={() => setShowCancelModal(false)}>Keep Running</button>
          <button className="btn-primary !bg-red-600 !border-red-600 hover:!bg-red-700" onClick={handleCancelConfirm}>Yes, Cancel</button>
        </div>
      </Modal>
    </div>
  )
}
