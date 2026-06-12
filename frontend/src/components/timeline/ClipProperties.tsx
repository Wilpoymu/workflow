import { useMemo } from "react"
import { useTimelineStore } from "../../stores/timelineStore"
import type { ClipMovement } from "../../types/timeline"

// ─── Movement options ──────────────────────────────────────────────────

const MOVEMENT_OPTIONS: { value: ClipMovement; label: string }[] = [
  { value: "zoom_in", label: "Zoom In" },
  { value: "zoom_out", label: "Zoom Out" },
  { value: "pan_left", label: "Pan Left" },
  { value: "pan_right", label: "Pan Right" },
  { value: "pan_up", label: "Pan Up" },
  { value: "pan_down", label: "Pan Down" },
]

// ─── X icon (inline SVG, no lucide dependency) ─────────────────────────

function XIcon() {
  return (
    <svg
      className="w-3.5 h-3.5"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  )
}

// ─── Film / clip icon for empty state ──────────────────────────────────

function ClipIcon() {
  return (
    <svg
      className="w-4 h-4 text-slate-500"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="2" width="20" height="20" rx="2" ry="2" />
      <path d="M8.5 14.5v-5l4 2.5-4 2.5z" />
    </svg>
  )
}

// ─── Section group ─────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[10px] font-semibold text-slate-600 uppercase tracking-widest">
        {label}
      </span>
      {children}
    </div>
  )
}

// ─── Read-only info row ────────────────────────────────────────────────

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-slate-500">{label}</span>
      <span
        className="text-[11px] text-slate-400 font-mono truncate max-w-[140px]"
        title={value}
      >
        {value}
      </span>
    </div>
  )
}

// ─── Main component ────────────────────────────────────────────────────

export default function ClipProperties() {
  const timeline = useTimelineStore((s) => s.timeline)
  const selectedClipId = useTimelineStore((s) => s.selectedClipId)
  const selectClip = useTimelineStore((s) => s.selectClip)
  const updateClip = useTimelineStore((s) => s.updateClip)

  // ── Find the selected clip across all tracks ──────────────────────
  const selectedClip = useMemo(() => {
    if (!timeline || !selectedClipId) return null
    for (const track of timeline.tracks) {
      const clip = track.clips.find((c) => c.id === selectedClipId)
      if (clip) return clip
    }
    return null
  }, [timeline, selectedClipId])

  // ── Empty state: no clip selected ─────────────────────────────────
  if (!selectedClip) {
    return (
      <div className="w-72 bg-slate-900 border-l border-slate-800 p-4 flex flex-col items-center justify-center text-center gap-2 shrink-0">
        <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center">
          <ClipIcon />
        </div>
        <p className="text-xs text-slate-500">Select a clip to edit</p>
      </div>
    )
  }

  const isImage = selectedClip.source_type === "image"

  // ── Properties panel ──────────────────────────────────────────────
  return (
    <div className="w-72 bg-slate-900 border-l border-slate-800 p-4 overflow-y-auto flex flex-col gap-4 shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Clip Properties
        </h2>
        <button
          type="button"
          className="text-slate-600 hover:text-slate-400 transition-colors"
          onClick={() => selectClip(null)}
        >
          <XIcon />
        </button>
      </div>

      {/* Source info (read-only) */}
      <Section label="Source">
        <InfoRow label="Type" value={selectedClip.source_type} />
        <InfoRow label="ID" value={selectedClip.id} />
        <InfoRow label="Path" value={selectedClip.source_path} />
      </Section>

      {/* Timing */}
      <Section label="Timing">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-500">Duration</span>
          <input
            type="number"
            className="w-20 px-2 py-1 text-xs bg-slate-800 rounded border border-slate-700 text-slate-200 text-right font-mono"
            value={parseFloat(selectedClip.duration.toFixed(1))}
            min={0.1}
            step={0.1}
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              if (val > 0) {
                updateClip(selectedClip.id, { duration: val })
              }
            }}
          />
        </div>
        <InfoRow label="Trim In" value={`${(selectedClip.trim_in ?? 0).toFixed(1)}s`} />
        <InfoRow label="Trim Out" value={`${(selectedClip.trim_out ?? selectedClip.duration ?? 0).toFixed(1)}s`} />
        <InfoRow label="Start" value={`${selectedClip.start_time.toFixed(1)}s`} />
      </Section>

      {/* Movement — only for image clips */}
      {isImage && (
        <Section label="Movement">
          <select
            className="w-full px-2 py-1.5 text-xs bg-slate-800 rounded border border-slate-700 text-slate-200"
            value={selectedClip.movement || "zoom_in"}
            onChange={(e) =>
              updateClip(selectedClip.id, {
                movement: e.target.value as ClipMovement,
              })
            }
          >
            {MOVEMENT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>

          {/* Intensity slider */}
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-slate-500">
              Intensity: {((selectedClip.intensity ?? 0.05) * 100).toFixed(0)}%
            </span>
            <input
              type="range"
              className="w-full accent-blue-500"
              min={1}
              max={15}
              value={Math.round((selectedClip.intensity ?? 0.05) * 100)}
              onChange={(e) =>
                updateClip(selectedClip.id, {
                  intensity: parseInt(e.target.value) / 100,
                })
              }
            />
          </div>
        </Section>
      )}
    </div>
  )
}
