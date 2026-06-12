import type React from "react"
import { useDraggable } from "@dnd-kit/core"
import type { TimelineClip } from "../../types/timeline"

// ─── Props ──────────────────────────────────────────────────────────

interface AudioTrackProps {
  clip: TimelineClip
  pixelsPerSecond: number
  isSelected: boolean
  onSelect: (id: string) => void
  onTrimStart: (clipId: string, edge: "in" | "out", e: React.MouseEvent<HTMLDivElement>) => void
}

// ─── Component ──────────────────────────────────────────────────────

/**
 * Audio waveform visualization for a single clip on the timeline.
 *
 * Phase 1: static uniform bars approximating amplitude.
 * Phase 2: pre-generated actual waveform data.
 */
export default function AudioTrack({
  clip,
  pixelsPerSecond: pps,
  isSelected,
  onSelect,
  onTrimStart,
}: AudioTrackProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: clip.id,
  })

  const duration = clip.duration ?? 0
  const width = Math.max(4, duration * pps)  // minimum 4px to stay clickable
  const barCount = Math.max(1, Math.min(Math.floor(width / 4), 100))

  // Generate pseudo-random but deterministic bar heights
  const bars: number[] = []
  for (let i = 0; i < barCount; i++) {
    const h = 0.3 + 0.7 * Math.abs(Math.sin(i * 2.7 + i * i * 0.01))
    bars.push(h)
  }

  const style: React.CSSProperties = {
    left: `${clip.start_time * pps}px`,
    width: `${width}px`,
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    zIndex: isDragging ? 50 : undefined,
    opacity: isDragging ? 0.8 : undefined,
  }

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`absolute top-1 bottom-1 rounded cursor-grab active:cursor-grabbing overflow-hidden bg-emerald-600/30
        ${isSelected ? "ring-2 ring-emerald-400" : ""}
        transition-colors duration-75`}
      style={style}
      onClick={() => onSelect(clip.id)}
    >
      {/* ── SVG waveform bars ───────────────────────────────────── */}
      <svg className="w-full h-full" viewBox={`0 0 ${barCount} 100`} preserveAspectRatio="none">
        {bars.map((h, i) => (
          <rect
            key={i}
            x={i}
            y={50 - h * 50}
            width={0.8}
            height={h * 100}
            fill="rgba(52, 211, 153, 0.4)" // emerald-400 at 40%
          />
        ))}
      </svg>

      {/* ── Duration label ──────────────────────────────────────── */}
      <span className="absolute inset-x-1 bottom-1 text-[9px] text-emerald-300/60 font-mono pointer-events-none">
        {(clip.duration ?? 0).toFixed(1)}s
      </span>

      {/* ── Trim handles ────────────────────────────────────────── */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[6px] cursor-col-resize hover:bg-white/20 rounded-l transition-colors"
        onPointerDown={(e) => {
          // Stop pointer event propagation so dnd-kit doesn't intercept
          e.stopPropagation()
        }}
        onMouseDown={(e) => {
          e.stopPropagation()
          onTrimStart(clip.id, "in", e)
        }}
      />
      <div
        className="absolute right-0 top-0 bottom-0 w-[6px] cursor-col-resize hover:bg-white/20 rounded-r transition-colors"
        onPointerDown={(e) => {
          // Stop pointer event propagation so dnd-kit doesn't intercept
          e.stopPropagation()
        }}
        onMouseDown={(e) => {
          e.stopPropagation()
          onTrimStart(clip.id, "out", e)
        }}
      />
    </div>
  )
}
