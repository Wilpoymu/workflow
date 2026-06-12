import { useEffect, useCallback, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import { Video, Save } from "lucide-react"
import { DndContext, DragOverlay, PointerSensor, useSensor, useSensors } from "@dnd-kit/core"
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core"
import { useTimelineStore } from "../stores/timelineStore"
import { api } from "../api/client"
import TimelineTrack from "../components/timeline/TimelineTrack"
import SubtitleTrack from "../components/timeline/SubtitleTrack"
import ClipProperties from "../components/timeline/ClipProperties"
import EmptyState from "../components/EmptyState"
import TimelineRuler from "../components/timeline/TimelineRuler"

export default function TimelinePage() {
  const { projectId } = useParams<{ projectId: string }>()

  // ── Store selectors ───────────────────────────────────────────────
  const timeline = useTimelineStore((s) => s.timeline)
  const isLoading = useTimelineStore((s) => s.isLoading)
  const isSaving = useTimelineStore((s) => s.isSaving)
  const error = useTimelineStore((s) => s.error)
  const playheadTime = useTimelineStore((s) => s.playheadTime)
  const pixelsPerSecond = useTimelineStore((s) => s.pixelsPerSecond)
  const selectedClipId = useTimelineStore((s) => s.selectedClipId)
  const selectClip = useTimelineStore((s) => s.selectClip)
  const reorderClip = useTimelineStore((s) => s.reorderClip)
  const trimClip = useTimelineStore((s) => s.trimClip)
  const splitClipAt = useTimelineStore((s) => s.splitClipAt)
  const setZoom = useTimelineStore((s) => s.setZoom)
  const loadTimeline = useTimelineStore((s) => s.loadTimeline)
  const saveTimeline = useTimelineStore((s) => s.saveTimeline)

  // ── Trim drag state ───────────────────────────────────────────────
  const [trimDrag, setTrimDrag] = useState<{
    clipId: string
    edge: "in" | "out"
    startX: number
  } | null>(null)
  const setPlayhead = useTimelineStore((s) => s.setPlayhead)

  // ── DnD state ─────────────────────────────────────────────────────
  const [activeId, setActiveId] = useState<string | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  )

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(String(event.active.id))
  }, [])

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveId(null)
      const { active, delta } = event

      const clipId = String(active.id)
      if (!timeline) return
      for (const track of timeline.tracks) {
        const oldIdx = track.clips.findIndex((c) => c.id === clipId)
        if (oldIdx === -1) continue

        const clip = track.clips[oldIdx]
        const clipWidth = Math.max(1, clip.duration * pixelsPerSecond)
        const indexShift = Math.round(delta.x / clipWidth)
        const newIdx = Math.max(0, Math.min(track.clips.length - 1, oldIdx + indexShift))
        if (newIdx === oldIdx) return

        reorderClip(clipId, track.id, newIdx)
        break
      }
    },
    [timeline, pixelsPerSecond, reorderClip],
  )

  const handleDragCancel = useCallback(() => {
    setActiveId(null)
  }, [])

  // ── Local UI state ────────────────────────────────────────────────
  const [isExporting, setIsExporting] = useState(false)
  const [exportMessage, setExportMessage] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; type: "error" | "success" } | null>(null)

  // ── Convert store errors to toasts (non-fatal) ────────────────────
  useEffect(() => {
    if (error && timeline) {
      setToast({ message: error, type: "error" })
      // Clear store error immediately since we've shown the toast
      useTimelineStore.getState().setError(null)
    }
  }, [error, timeline])

  const duration = timeline?.duration ?? 0
  const totalWidth = Math.max(duration * pixelsPerSecond, 800)

  // ── Load timeline on mount ────────────────────────────────────────
  useEffect(() => {
    if (projectId) loadTimeline(projectId)
  }, [projectId, loadTimeline])

  // ── Auto-save with 2s debounce on timeline changes ───────────────
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevTimelineRef = useRef(timeline)

  useEffect(() => {
    if (!timeline || !projectId) return

    // Skip initial load — compare by reference
    if (prevTimelineRef.current === timeline) return
    prevTimelineRef.current = timeline

    // Debounce save
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      saveTimeline(projectId)
    }, 2000)

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [timeline, projectId, saveTimeline])

  // ── Export handler ────────────────────────────────────────────────
  const handleExport = useCallback(async () => {
    if (!projectId) return
    setIsExporting(true)
    setExportMessage("Starting render...")
    try {
      const res = await api.exportTimeline(projectId)
      if (res.ok) {
        setExportMessage("Render complete! Output: " + (res.output || "ready"))
        // Connect SSE for progress updates (if available on backend)
        api.connectExportSSE(projectId, {
          onProgress: (progress, message) => {
            setExportMessage(`Rendering: ${Math.round(progress * 100)}% - ${message}`)
          },
          onComplete: (output) => {
            setExportMessage("Render complete! Output: " + output)
            setIsExporting(false)
            setTimeout(() => setExportMessage(null), 3000)
          },
          onError: (message) => {
            setExportMessage("Render failed: " + message)
            setIsExporting(false)
            setTimeout(() => setExportMessage(null), 5000)
          },
        })
      } else {
        setExportMessage("Export failed: " + (res.message || "Unknown error"))
      }
    } catch (e) {
      setExportMessage("Export error: " + String(e))
    } finally {
      setTimeout(() => {
        setIsExporting(false)
        setExportMessage(null)
      }, 3000)
    }
  }, [projectId])

  // ── Split handler ─────────────────────────────────────────────────
  const handleSplit = useCallback(() => {
    if (!timeline) return
    const videoTrack = timeline.tracks.find((t) => t.type === "video")
    if (!videoTrack) return
    splitClipAt(videoTrack.id, playheadTime)
  }, [timeline, playheadTime, splitClipAt])

  const zoomOptions = [
    { label: "1x", value: 50 },
    { label: "2x", value: 100 },
    { label: "4x", value: 200 },
  ] as const

  // ── Trim drag handlers ────────────────────────────────────────────
  const handleTrimStart = useCallback(
    (clipId: string, edge: "in" | "out", e: React.MouseEvent<HTMLDivElement>) => {
      e.preventDefault()
      setTrimDrag({ clipId, edge, startX: e.clientX })
    },
    [],
  )

  // Track mouse move/up during trim drag
  useEffect(() => {
    if (!trimDrag) return

    const handleMouseMove = (e: MouseEvent) => {
      const deltaSec = (e.clientX - trimDrag.startX) / pixelsPerSecond
      // Minimum threshold of 1 frame at 30fps before applying
      if (Math.abs(deltaSec) > 0.033) {
        trimClip(trimDrag.clipId, trimDrag.edge, deltaSec)
        setTrimDrag((prev) => (prev ? { ...prev, startX: e.clientX } : prev))
      }
    }

    const handleMouseUp = () => {
      setTrimDrag(null)
    }

    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
    }
  }, [trimDrag, pixelsPerSecond, trimClip])

  // ── Loading state ─────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-slate-400 font-mono">Loading timeline...</span>
        </div>
      </div>
    )
  }

  // ── Fatal error state (no timeline at all) ─────────────────────────
  if (error && !timeline) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <div className="flex flex-col items-center gap-3">
          <div className="text-red-400 text-sm font-mono">{error}</div>
          <button
            className="btn-secondary text-xs"
            onClick={() => projectId && loadTimeline(projectId)}
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  // ── Empty / no timeline state ─────────────────────────────────────
  if (!timeline) {
    return (
      <div className="bg-slate-950 h-screen">
        <EmptyState
          icon={<Video />}
          title="No timeline data"
          description="Make sure the project has fragments before opening the Timeline Editor."
        />
      </div>
    )
  }

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen bg-slate-950">
      {/* ── Toast notification ─────────────────────────────────────── */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-2 rounded shadow-lg text-sm flex items-center gap-2
            ${toast.type === "error" ? "bg-red-600 text-white" : "bg-emerald-600 text-white"}`}
        >
          <span>{toast.message}</span>
          <button className="text-white/70 hover:text-white" onClick={() => setToast(null)}>
            ×
          </button>
        </div>
      )}

      {/* ── Export progress indicator ──────────────────────────────── */}
      {exportMessage && (
        <div className="fixed bottom-4 right-4 z-50 px-4 py-2 bg-slate-800 border border-slate-700 text-slate-200 rounded-lg shadow-lg text-xs font-mono flex items-center gap-2">
          {isExporting && (
            <div className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          )}
          <span>{exportMessage}</span>
        </div>
      )}

      {/* ── Header ────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-sm font-semibold text-slate-200 font-sans whitespace-nowrap">
            Timeline Editor
          </h1>
          <span className="text-xs text-slate-500 font-mono whitespace-nowrap">
            {timeline.canvas.width}&times;{timeline.canvas.height} @ {timeline.canvas.fps}fps
          </span>
          <span className="text-xs text-slate-600 font-mono">
            {(duration / 60).toFixed(1)}m
          </span>
        </div>

        <div className="flex items-center gap-2">
          {isSaving && (
            <span className="flex items-center gap-1.5 text-xs text-slate-500 font-mono">
              <Save className="w-3 h-3" />
              Saving...
            </span>
          )}
          <button
            className="btn-secondary text-xs"
            onClick={handleSplit}
            title="Split clip at playhead"
          >
            Split
          </button>
          <div className="flex items-center gap-1">
            {zoomOptions.map((opt) => (
              <button
                key={opt.value}
                className={`px-2 py-0.5 text-[11px] rounded font-medium transition-colors
                  ${pixelsPerSecond === opt.value
                    ? "bg-blue-500/20 text-blue-400"
                    : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"}`}
                onClick={() => setZoom(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            className="btn-primary text-xs"
            onClick={handleExport}
            disabled={isExporting}
          >
            {isExporting ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <Video className="w-3.5 h-3.5" />
                Export Video
              </>
            )}
          </button>
        </div>
      </header>

      {/* ── Main content ──────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Timeline tracks area (scrollable) */}
        <div className="flex-1 overflow-x-auto overflow-y-auto">
          <div
            style={{ width: `${totalWidth}px`, minHeight: "100%" }}
            className="relative"
          >
            {/* Ruler */}
            <div className="sticky top-0 z-20">
              <TimelineRuler
                duration={duration}
                pixelsPerSecond={pixelsPerSecond}
                playheadTime={playheadTime}
                onPlayheadChange={setPlayhead}
              />
            </div>

            {/* Tracks */}
            <DndContext
              sensors={sensors}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
              onDragCancel={handleDragCancel}
            >
              {timeline.tracks.map((track) => {
                if (track.type === "subtitle") {
                  return (
                    <SubtitleTrack
                      key={track.id}
                      track={track}
                      pixelsPerSecond={pixelsPerSecond}
                    />
                  )
                }
                return (
                  <TimelineTrack
                    key={track.id}
                    track={track}
                    pixelsPerSecond={pixelsPerSecond}
                    selectedClipId={selectedClipId}
                    onSelectClip={selectClip}
                    onTrimStart={handleTrimStart}
                  />
                )
              })}

              <DragOverlay>
                {activeId ? (
                  <div className="w-40 h-12 rounded bg-blue-500/30 border-2 border-blue-400" />
                ) : null}
              </DragOverlay>
            </DndContext>

            {/* Empty tracks notice */}
            {timeline.tracks.length === 0 && (
              <div className="flex items-center justify-center h-32 text-slate-600 text-xs font-mono">
                No tracks — add fragments to the project first
              </div>
            )}
          </div>
        </div>

        {/* Properties side panel */}
        <ClipProperties />
      </div>
    </div>
  )
}
