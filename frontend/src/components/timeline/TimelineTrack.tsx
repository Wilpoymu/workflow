import { useState, useRef, Fragment } from "react"
import type React from "react"
import type { Track, Transition } from "../../types/timeline"
import TimelineClip from "./TimelineClip"
import AudioTrack from "./AudioTrack"
import TransitionBadge from "./TransitionBadge"
import TransitionPicker from "./TransitionPicker"

// ─── Props ──────────────────────────────────────────────────────────

interface TimelineTrackProps {
  track: Track
  pixelsPerSecond: number
  selectedClipId: string | null
  onSelectClip: (clipId: string) => void
  onTrimStart: (
    clipId: string,
    edge: "in" | "out",
    e: React.MouseEvent<HTMLDivElement>,
  ) => void
  onSetTransition?: (clipId: string, transition: Transition | null) => void
  /** Future: drag-drop from media browser */
  onDrop?: (trackId: string, timeSec: number) => void
}

// ─── Transition zone state ──────────────────────────────────────────

interface PickerState {
  clipId: string
  position: { x: number; y: number }
  transition?: Transition
}

// ─── Component ──────────────────────────────────────────────────────

export default function TimelineTrack({
  track,
  pixelsPerSecond: pps,
  selectedClipId,
  onSelectClip,
  onTrimStart,
  onSetTransition,
}: TimelineTrackProps) {
  const [pickerState, setPickerState] = useState<PickerState | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleOpenPicker = (
    clipId: string,
    el: HTMLElement,
    existing?: Transition,
  ) => {
    const rect = el.getBoundingClientRect()
    setPickerState({
      clipId,
      position: {
        x: Math.max(8, rect.left + rect.width / 2 - 144), // center 288px panel
        y: rect.top - 50,
      },
      transition: existing,
    })
  }

  const handleSaveTransition = (transition: Transition) => {
    if (!pickerState) return
    onSetTransition?.(pickerState.clipId, transition)
    setPickerState(null)
  }

  const handleRemoveTransition = () => {
    if (!pickerState) return
    onSetTransition?.(pickerState.clipId, null)
    setPickerState(null)
  }

  return (
    <div
      ref={containerRef}
      className="relative h-16 bg-slate-950/50 border-b border-slate-800/50"
    >
      {/* ── Track label overlay ──────────────────────────────────── */}
      <div className="absolute left-0 top-0 bottom-0 w-20 z-10 bg-slate-900/80 flex items-center px-2">
        <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wider truncate">
          {track.name}
        </span>
      </div>

      {/* ── Clips container ──────────────────────────────────────── */}
      <div className="absolute left-20 right-0 top-0 bottom-0">
        {track.clips.length > 0 ? (
          <div className="relative h-full">
            {track.clips.map((clip, index) => {
              const isAudio = clip.source_type === "audio"
              const ClipComponent = isAudio ? AudioTrack : TimelineClip
              const hasTransition = !!clip.transition_out

              return (
                <Fragment key={clip.id}>
                  {/* ── Clip ───────────────────────────────────── */}

                  <ClipComponent
                    clip={clip}
                    pixelsPerSecond={pps}
                    isSelected={clip.id === selectedClipId}
                    onSelect={onSelectClip}
                    onTrimStart={onTrimStart}
                  />

                  {/* ── Transition zone (between clips) ─────────── */}
                  {index < track.clips.length - 1 && (
                    <TransitionZone
                      left={clip.start_time + clip.duration}
                      hasTransition={hasTransition}
                      pixelsPerSecond={pps}
                      onOpen={(el) =>
                        handleOpenPicker(
                          clip.id,
                          el,
                          clip.transition_out,
                        )
                      }
                    />
                  )}

                  {/* ── Transition badge (when one exists) ──────── */}
                  {hasTransition && (
                    <TransitionBadgeZone
                      left={clip.start_time + clip.duration}
                      transition={clip.transition_out!}
                      pixelsPerSecond={pps}
                      onOpen={(el) =>
                        handleOpenPicker(
                          clip.id,
                          el,
                          clip.transition_out,
                        )
                      }
                      onRemove={() =>
                        onSetTransition?.(clip.id, null)
                      }
                    />
                  )}
                </Fragment>
              )
            })}
          </div>
        ) : (
          /* Empty track state */
          <div className="flex items-center justify-center h-full text-[10px] text-slate-700 font-mono select-none">
            No clips
          </div>
        )}
      </div>

      {/* ── Transition picker overlay ────────────────────────────── */}
      {pickerState && (
        <TransitionPicker
          position={pickerState.position}
          transition={pickerState.transition}
          onSave={handleSaveTransition}
          onRemove={handleRemoveTransition}
          onClose={() => setPickerState(null)}
        />
      )}
    </div>
  )
}

// ─── TransitionZone sub-component ───────────────────────────────────

/**
 * Invisible hover zone between two clips. Shows a "+" button on hover
 * so users can add a transition.
 */
function TransitionZone({
  left,
  hasTransition,
  pixelsPerSecond: pps,
  onOpen,
}: {
  left: number
  hasTransition: boolean
  pixelsPerSecond: number
  onOpen: (el: HTMLElement) => void
}) {
  const [hovering, setHovering] = useState(false)
  const zoneRef = useRef<HTMLDivElement>(null)
  const zoneWidth = 14

  const pixelLeft = left * pps - zoneWidth / 2

  // Don't show the zone on the timeline edge
  if (pixelLeft < 0) return null

  return (
    <div
      ref={zoneRef}
      className="absolute top-0 bottom-0 z-20"
      style={{
        left: `${pixelLeft}px`,
        width: `${zoneWidth}px`,
      }}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      {/* Clickable hotspot */}
      <button
        onClick={() => {
          if (zoneRef.current) onOpen(zoneRef.current)
        }}
        className={`
          absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
          flex items-center justify-center
          w-5 h-5 rounded-full
          transition-all duration-100
          ${
            hovering
              ? "opacity-100 scale-100 bg-slate-700/80 border border-slate-500/50"
              : hasTransition
                ? "opacity-0 scale-75"
                : "opacity-0 scale-75"
          }
        `}
        title="Add transition"
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          className="text-slate-300"
        >
          <path d="M5 1v8M1 5h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  )
}

// ─── TransitionBadgeZone sub-component ──────────────────────────────

/**
 * Renders the TransitionBadge pill centered between two clips at the
 * boundary position. Clicking it opens the TransitionPicker; the X
 * removes the transition.
 */
function TransitionBadgeZone({
  left,
  transition,
  pixelsPerSecond: pps,
  onOpen,
  onRemove,
}: {
  left: number
  transition: Transition
  pixelsPerSecond: number
  onOpen: (el: HTMLElement) => void
  onRemove: () => void
}) {
  const badgeRef = useRef<HTMLDivElement>(null)
  const pixelLeft = left * pps

  return (
    <div
      ref={badgeRef}
      className="absolute z-20"
      style={{
        left: `${pixelLeft}px`,
        top: "50%",
        transform: "translate(-50%, -50%)",
      }}
    >
      <TransitionBadge
        transition={transition}
        onClick={() => {
          if (badgeRef.current) onOpen(badgeRef.current)
        }}
        onRemove={onRemove}
      />
    </div>
  )
}
