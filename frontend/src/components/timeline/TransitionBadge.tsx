import { X } from "lucide-react"
import type { Transition } from "../../types/timeline"
import { TRANSITION_LABELS } from "../../types/timeline"

// ─── Props ──────────────────────────────────────────────────────────

interface TransitionBadgeProps {
  transition: Transition
  onClick: () => void
  onRemove: () => void
}

// ─── Component ──────────────────────────────────────────────────────

/**
 * Small pill badge shown between two clips when a transition exists.
 * Clicking opens the TransitionPicker; the X button removes it.
 */
export default function TransitionBadge({
  transition,
  onClick,
  onRemove,
}: TransitionBadgeProps) {
  return (
    <div
      className="
        group inline-flex items-center gap-1
        px-1.5 py-0.5 rounded-full
        bg-cyan-500/20 border border-cyan-500/30
        text-[10px] text-cyan-300 font-medium
        cursor-pointer select-none
        hover:bg-cyan-500/30 hover:border-cyan-500/50
        transition-colors duration-100
      "
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick() }}
      title={`Transition: ${TRANSITION_LABELS[transition.type]} (${transition.duration.toFixed(1)}s)`}
    >
      <span className="truncate max-w-[64px]">
        {TRANSITION_LABELS[transition.type]}
      </span>
      <span className="text-[9px] text-cyan-400/60">
        {transition.duration.toFixed(1)}s
      </span>

      {/* Remove button */}
      <button
        className="
          ml-0.5 p-[1px] rounded-full
          text-cyan-400/50 hover:text-cyan-200 hover:bg-cyan-500/30
          transition-colors
        "
        onClick={(e) => {
          e.stopPropagation()
          onRemove()
        }}
        title="Remove transition"
      >
        <X size={10} aria-hidden="true" />
      </button>
    </div>
  )
}
