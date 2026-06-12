import type React from "react"
import { useDraggable } from "@dnd-kit/core"
import type { TimelineClip, ClipSourceType } from "../../types/timeline"

// ─── Props ──────────────────────────────────────────────────────────

interface TimelineClipProps {
  clip: TimelineClip
  pixelsPerSecond: number
  isSelected: boolean
  onSelect: (id: string) => void
  onTrimStart: (clipId: string, edge: "in" | "out", e: React.MouseEvent<HTMLDivElement>) => void
}

// ─── Clip colours by source type ────────────────────────────────────
// "image" is a visual clip (same as video would be) → blue-600
// "audio" → emerald-600, "subtitle" → amber-600

const CLIP_BG: Record<ClipSourceType, string> = {
  image:    "bg-blue-600/80 hover:bg-blue-600/90",
  audio:    "bg-emerald-600/80 hover:bg-emerald-600/90",
  subtitle: "bg-amber-600/80 hover:bg-amber-600/90",
}

const CLIP_INNER_GRADIENT: Record<ClipSourceType, string> = {
  image:    "bg-gradient-to-b from-white/[0.08] to-transparent",
  audio:    "bg-gradient-to-b from-white/[0.08] to-transparent",
  subtitle: "bg-gradient-to-b from-white/[0.08] to-transparent",
}

// ─── Component ──────────────────────────────────────────────────────

export default function TimelineClip({
  clip,
  pixelsPerSecond: pps,
  isSelected,
  onSelect,
  onTrimStart,
}: TimelineClipProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: clip.id,
  })

  const left = clip.start_time * pps
  const width = clip.duration * pps

  const style: React.CSSProperties = {
    left: `${left}px`,
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
      className={`
        absolute top-1 bottom-1 rounded cursor-grab active:cursor-grabbing overflow-hidden
        ${CLIP_BG[clip.source_type]}
        ${CLIP_INNER_GRADIENT[clip.source_type]}
        ${isSelected ? "ring-2 ring-blue-400" : ""}
        transition-colors duration-75
      `}
      style={style}
      onClick={(e) => {
        e.stopPropagation()
        onSelect(clip.id)
      }}
    >
      {/* ── Clip label ──────────────────────────────────────────── */}
      <span className="absolute inset-x-1 top-1 text-[10px] text-white/90 truncate font-medium">
        {clip.source_type === "subtitle" && clip.text
          ? clip.text
          : `${clip.source_type} ${clip.id.replace("clip_", "#")}`}
      </span>

      <span className="absolute inset-x-1 bottom-1 text-[9px] text-white/60 font-mono">
        {clip.duration.toFixed(1)}s
      </span>

      {/* ── Trim handles ────────────────────────────────────────── */}
      {/* Left trim handle (trim-in) */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[6px] cursor-col-resize hover:bg-white/20 active:bg-white/30 rounded-l transition-colors"
        onPointerDown={(e) => {
          // Stop pointer event propagation so dnd-kit doesn't intercept
          e.stopPropagation()
        }}
        onMouseDown={(e) => {
          e.stopPropagation()
          onTrimStart(clip.id, "in", e)
        }}
      />

      {/* Right trim handle (trim-out) */}
      <div
        className="absolute right-0 top-0 bottom-0 w-[6px] cursor-col-resize hover:bg-white/20 active:bg-white/30 rounded-r transition-colors"
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
