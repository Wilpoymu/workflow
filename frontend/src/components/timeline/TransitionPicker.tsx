import { useState, useEffect, useRef } from "react"
import { X, Trash2 } from "lucide-react"
import type { Transition, TransitionType } from "../../types/timeline"
import { TRANSITION_LABELS } from "../../types/timeline"

// ─── Constants ──────────────────────────────────────────────────────

const TRANSITION_TYPES: TransitionType[] = [
  "fade",
  "fadeblack",
  "fadewhite",
  "dissolve",
  "wipeleft",
  "wiperight",
  "wipeup",
  "wipedown",
  "slideleft",
  "slideright",
  "slideup",
  "slidedown",
  "pixelize",
]

const MIN_DURATION = 0.1
const MAX_DURATION = 2.0
const DURATION_STEP = 0.1

// ─── Props ──────────────────────────────────────────────────────────

interface TransitionPickerProps {
  /** Where to show the popup — viewport coordinates */
  position: { x: number; y: number }
  /** Existing transition to edit (undefined = new transition) */
  transition?: Transition
  onSave: (transition: Transition) => void
  onRemove: () => void
  onClose: () => void
}

// ─── Component ──────────────────────────────────────────────────────

export default function TransitionPicker({
  position,
  transition,
  onSave,
  onRemove,
  onClose,
}: TransitionPickerProps) {
  const [type, setType] = useState<TransitionType>(transition?.type ?? "fade")
  const [duration, setDuration] = useState<number>(
    transition?.duration ?? 0.5,
  )
  const panelRef = useRef<HTMLDivElement>(null)

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  // Close on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    // Delay so the picker's own open click doesn't immediately close it
    const id = window.setTimeout(() => {
      window.addEventListener("mousedown", handler)
    }, 0)
    return () => {
      window.clearTimeout(id)
      window.removeEventListener("mousedown", handler)
    }
  }, [onClose])

  const handleSave = () => {
    onSave({ type, duration })
  }

  return (
    <div
      ref={panelRef}
      className="
        fixed z-[100] w-72
        bg-surface-card border border-border rounded-lg
        shadow-lg shadow-black/40
        p-3
      "
      style={{ left: position.x, top: position.y }}
    >
      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-semibold text-ink-dim uppercase tracking-wider">
          Transition
        </span>
        <button
          className="p-0.5 rounded text-ink-faint hover:text-ink-dim hover:bg-surface-elevated transition-colors"
          onClick={onClose}
          title="Close"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>

      {/* ── Type selector (grid) ────────────────────────────────── */}
      <label className="block text-[10px] font-medium text-ink-dim mb-1.5 uppercase tracking-wider">
        Type
      </label>
      <div className="grid grid-cols-4 gap-1 mb-3">
        {TRANSITION_TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setType(t)}
            className={`
              px-1 py-1.5 rounded text-[10px] font-medium
              transition-colors duration-75
              ${
                type === t
                  ? "bg-cyan-600/30 text-cyan-300 border border-cyan-500/40"
                  : "bg-surface-elevated text-ink-dim border border-transparent hover:bg-surface-hover hover:text-ink"
              }
            `}
            title={TRANSITION_LABELS[t]}
          >
            {TRANSITION_LABELS[t]}
          </button>
        ))}
      </div>

      {/* ── Duration slider ─────────────────────────────────────── */}
      <label className="block text-[10px] font-medium text-ink-dim mb-1.5 uppercase tracking-wider">
        Duration
      </label>
      <div className="flex items-center gap-2 mb-3">
        <input
          type="range"
          min={MIN_DURATION}
          max={MAX_DURATION}
          step={DURATION_STEP}
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          className="
            flex-1 h-1.5 appearance-none
            bg-surface-hover rounded-full
            accent-cyan-500
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-3.5
            [&::-webkit-slider-thumb]:h-3.5
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:bg-cyan-400
            [&::-webkit-slider-thumb]:shadow-sm
            [&::-webkit-slider-thumb]:cursor-pointer
          "
        />
        <span className="w-10 text-right text-[11px] text-ink-dim font-mono tabular-nums">
          {duration.toFixed(1)}s
        </span>
      </div>

      {/* ── Preview ─────────────────────────────────────────────── */}
      <div className="mb-3 px-2 py-1.5 rounded bg-surface-elevated/60 border border-border/50">
        <span className="text-[10px] text-ink-dim">
          {TRANSITION_LABELS[type]}{" "}
          <span className="text-ink-faint">·</span>{" "}
          <span className="text-ink-faint">{duration.toFixed(1)}s</span>
        </span>
      </div>

      {/* ── Actions ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2">
        <button
          onClick={handleSave}
          className="
            flex-1 px-3 py-1.5 rounded
            bg-cyan-600 hover:bg-cyan-500
            text-[11px] font-semibold text-ink
            transition-colors
          "
        >
          Apply
        </button>
        <button
          onClick={onRemove}
          className="
            px-2 py-1.5 rounded
            bg-danger/25 hover:bg-danger/45
            text-danger hover:text-danger
            text-[11px] font-medium
            transition-colors
          "
          title="Remove transition"
        >
          <Trash2 size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
