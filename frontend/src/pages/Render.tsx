import { useEffect, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import { Video, Download, Play, AlertCircle, CheckCircle, Check, RefreshCw, Trash2 } from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import ProgressBar from "../components/ProgressBar"
import VideoPlayer from "../components/VideoPlayer"
import EmptyState from "../components/EmptyState"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"

type RenderStatus = "idle" | "running" | "done" | "failed"

interface RenderConfig {
  filter_mode: "all" | "even" | "odd"
  width: number
  height: number
  fps: number
  intensity: number
  seed: number
  subtitles: boolean
}

export default function Render() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [status, setStatus] = useState<RenderStatus>("idle")
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState("")
  const [hasRender, setHasRender] = useState(false)
  const [fileSize, setFileSize] = useState(0)
  const [projectTitle, setProjectTitle] = useState("")
  const [config, setConfig] = useState<RenderConfig>({
    filter_mode: "all",
    width: 1920,
    height: 1080,
    fps: 30,
    intensity: 0.04,
    seed: 42,
    subtitles: true,
  })

  const wsRef = useRef<WebSocket | null>(null)

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
    api.getRenderStatus(projectId).then((res) => {
      if (res.has_render) {
        setHasRender(true)
        setFileSize(res.file_size_mb ?? 0)
        setStatus("done")
      }
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    return () => { wsRef.current?.close() }
  }, [])

  const connectWS = () => {
    if (!projectId) return
    wsRef.current?.close()
    const ws = new WebSocket(api.renderWsUrl(projectId))
    wsRef.current = ws

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === "progress") {
        setProgress(data.progress * 100)
        setMessage(data.message)
        setStatus("running")
      } else if (data.type === "complete") {
        setStatus("done")
        setProgress(100)
        setMessage("Render complete")
        setHasRender(true)
        toast("Render completed successfully!", "success")
        api.getRenderStatus(projectId).then((res) => {
          if (res.file_size_mb) setFileSize(res.file_size_mb)
        })
      } else if (data.type === "error") {
        setStatus("failed")
        setMessage(data.message)
        toast(`Render failed: ${data.message}`, "error")
      }
    }

    ws.onerror = () => setStatus("failed")
  }

  const handleStartRender = async () => {
    if (!projectId) return

    connectWS()

    try {
      await api.startRender(projectId, config)
      setStatus("running")
      setProgress(0)
      setMessage("Starting render...")
    } catch (err: any) {
      setStatus("failed")
      setMessage(err?.message ?? "Failed to start render")
      toast(err?.message ?? "Failed to start render", "error")
    }
  }

  const handleDeleteRender = async () => {
    if (!projectId) return
    try {
      await api.deleteRender(projectId)
      setHasRender(false)
      setFileSize(0)
      setStatus("idle")
      setProgress(0)
      setMessage("")
      toast("Render deleted", "success")
    } catch {
      toast("Failed to delete render", "error")
    }
  }

  const handleDownload = () => {
    if (!projectId) return
    window.open(api.renderDownloadUrl(projectId), "_blank")
  }

  const updateConfig = <K extends keyof RenderConfig>(key: K, value: RenderConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }))
  }

  if (!projectId) {
    return (
      <EmptyState
        icon={<Video />}
        title="No project selected"
        description="Select a project from the Dashboard to render video"
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Ken Burns Render"}
        description="Generate final video with zoom-pan effects and synchronized audio"
        backTo={`/editor/${projectId}`}
        actions={
          <div className="flex items-center gap-2">
            {hasRender && (
              <>
                <button className="btn-secondary text-xs" onClick={handleDownload}>
                  <Download className="w-3.5 h-3.5" />
                  Download
                </button>
                <button
                  className="btn-secondary text-xs !text-red-400 hover:!bg-red-500/10"
                  onClick={handleDeleteRender}
                  title="Delete current render"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
            <button
              className="btn-primary"
              onClick={handleStartRender}
              disabled={status === "running"}
            >
              {status === "running" ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Rendering...
                </>
              ) : (
                <>
                  {hasRender ? <RefreshCw className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                  {hasRender ? "Re-render" : "Start Render"}
                </>
              )}
            </button>
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Image Selection */}
          <Card>
            <h3 className="text-sm font-semibold text-white mb-4 font-sans">
              Image Selection
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">
                  Filter Mode
                </label>
                <select
                  className="input"
                  value={config.filter_mode}
                  onChange={(e) => updateConfig("filter_mode", e.target.value as "all" | "even" | "odd")}
                  disabled={status === "running"}
                >
                  <option value="all">All images (01, 02, 03...)</option>
                  <option value="even">Even only (02, 04, 06...)</option>
                  <option value="odd">Odd only (01, 03, 05...)</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">
                  Random Seed
                </label>
                <input
                  type="number"
                  className="input"
                  value={config.seed}
                  onChange={(e) => updateConfig("seed", parseInt(e.target.value))}
                  min="1"
                  max="9999"
                  disabled={status === "running"}
                />
              </div>
            </div>
          </Card>

          {/* Video Settings */}
          <Card>
            <h3 className="text-sm font-semibold text-white mb-4 font-sans">
              Video Settings
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">
                  Resolution
                </label>
                <select
                  className="input"
                  value={`${config.width}x${config.height}`}
                  onChange={(e) => {
                    const [w, h] = e.target.value.split("x").map(Number)
                    setConfig((prev) => ({ ...prev, width: w, height: h }))
                  }}
                  disabled={status === "running"}
                >
                  <option value="1280x720">1280x720 (HD)</option>
                  <option value="1920x1080">1920x1080 (Full HD)</option>
                  <option value="3840x2160">3840x2160 (4K)</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">
                  FPS
                </label>
                <select
                  className="input"
                  value={config.fps}
                  onChange={(e) => updateConfig("fps", parseInt(e.target.value))}
                  disabled={status === "running"}
                >
                  <option value="24">24 (Cinema)</option>
                  <option value="30">30 (Standard)</option>
                  <option value="60">60 (Smooth)</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">
                  Movement Intensity
                </label>
                <input
                  type="range"
                  className="w-full"
                  min="0.01"
                  max="0.15"
                  step="0.01"
                  value={config.intensity}
                  onChange={(e) => updateConfig("intensity", parseFloat(e.target.value))}
                  disabled={status === "running"}
                />
                <span className="text-xs text-gray-400 font-mono">
                  {(config.intensity * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    className="w-4 h-4 rounded border-border bg-surface-hover text-accent focus:ring-accent"
                    checked={config.subtitles}
                    onChange={(e) => updateConfig("subtitles", e.target.checked)}
                    disabled={status === "running"}
                  />
                  <span className="text-sm text-gray-300">Burn subtitles</span>
                </label>
              </div>
            </div>
          </Card>

          {/* Progress */}
          <Card>
            <h3 className="text-sm font-semibold text-white mb-4 font-sans">Progress</h3>
            <ProgressBar progress={progress} />
            <div className="mt-4 flex items-center gap-3 text-xs text-gray-600 font-mono">
              <span>Status: {status}</span>
              {message && <span>• {message}</span>}
            </div>
            {status === "failed" && (
              <div className="mt-3 flex items-center gap-2 text-red-400 text-xs">
                <AlertCircle className="w-4 h-4" />
                <span>{message}</span>
              </div>
            )}
          </Card>
        </div>

        {/* Preview Panel */}
        <div className="space-y-4">
          {hasRender ? (
            <>
              <VideoPlayer
                src={api.renderDownloadUrl(projectId)}
                className="aspect-video"
              />
              <Card>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider font-sans">
                    Video Info
                  </span>
                  <span className="text-xs text-gray-300 font-mono">{fileSize} MB</span>
                </div>
              </Card>
            </>
          ) : (
            <Card className="p-0 overflow-hidden">
              <div className="aspect-video bg-surface-elevated flex items-center justify-center">
                <Video className="w-12 h-12 text-gray-800" />
              </div>
              <div className="p-4">
                <h3 className="text-sm font-semibold text-white font-sans">Preview</h3>
                <p className="text-xs text-gray-600 font-body mt-1">
                  Render output will appear here
                </p>
              </div>
            </Card>
          )}

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
              ) : status === "running" ? (
                <span className="text-xs text-accent font-mono">Rendering...</span>
              ) : (
                <span className="text-xs text-gray-500 font-mono">Idle</span>
              )}
            </div>
          </Card>

          {/* Features Info */}
          <Card>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 font-sans">
              Features
            </h3>
            <ul className="space-y-3 text-xs text-gray-400">
              <li className="flex items-center gap-2">
                <Check className="w-3.5 h-3.5 text-accent shrink-0" />
                Auto-sync with Whisper transcription
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-3.5 h-3.5 text-accent shrink-0" />
                6 movement types (zoom/pan)
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-3.5 h-3.5 text-accent shrink-0" />
                Smoothstep anti-jitter
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-3.5 h-3.5 text-accent shrink-0" />
                2x render + downscale (sub-pixel)
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-3.5 h-3.5 text-accent shrink-0" />
                GPU acceleration (NVENC/AMF)
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-3.5 h-3.5 text-accent shrink-0" />
                Optional subtitle burn-in
              </li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}
