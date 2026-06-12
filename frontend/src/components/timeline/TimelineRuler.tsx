import { useRef, useState, useEffect } from "react"

/** Width of track name labels in pixels (matches w-20 in Tailwind = 5rem = 80px) */
const LABEL_WIDTH = 80

interface TimelineRulerProps {
  /** Total timeline duration in seconds */
  duration: number
  /** Current zoom level — pixels per second */
  pixelsPerSecond: number
  /** Current playhead position in seconds */
  playheadTime: number
  /** Called when the user clicks or drags to a new time */
  onPlayheadChange: (time: number) => void
}

/**
 * CapCut-style timeline ruler.
 *
 * Draws major/minor tick marks, MM:SS labels, and a draggable playhead.
 * The playhead snaps to the clicked/dragged position on mousedown + mousemove.
 */
export default function TimelineRuler({
  duration,
  pixelsPerSecond,
  playheadTime,
  onPlayheadChange,
}: TimelineRulerProps) {
  const rulerRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  // ── Tick generation ───────────────────────────────────────────────

  const tickInterval = getTickInterval(pixelsPerSecond)

  const ticks: { time: number; isMajor: boolean }[] = []
  for (let t = 0; t <= duration; t += 1) {
    if (t % tickInterval === 0) {
      ticks.push({ time: t, isMajor: true })
    } else {
      ticks.push({ time: t, isMajor: false })
    }
  }

  // ── Position helpers ──────────────────────────────────────────────

  /** Convert a clientX pixel coordinate to a clamped time value */
  const timeFromPosition = (clientX: number): number => {
    if (!rulerRef.current) return 0
    const rect = rulerRef.current.getBoundingClientRect()
    const offsetX = clientX - rect.left - LABEL_WIDTH
    return Math.max(0, Math.min(duration, offsetX / pixelsPerSecond))
  }

  // ── Mouse interaction ─────────────────────────────────────────────

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true)
    onPlayheadChange(timeFromPosition(e.clientX))
  }

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      onPlayheadChange(timeFromPosition(e.clientX))
    }

    const handleMouseUp = () => {
      setIsDragging(false)
    }

    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)

    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
    }
  }, [isDragging])

  // ── Render ────────────────────────────────────────────────────────

  const totalWidth = Math.max(duration * pixelsPerSecond, 800) + LABEL_WIDTH

  return (
    <div
      ref={rulerRef}
      className="relative h-8 bg-slate-900 border-b border-slate-800 select-none cursor-pointer overflow-hidden"
      onMouseDown={handleMouseDown}
    >
      <div className="relative h-full" style={{ width: `${totalWidth}px` }}>
        {/* Spacer matching track label width — keeps 00:00 aligned with clip start */}
        <div className="absolute left-0 top-0 bottom-0 w-20 bg-slate-900 z-10" />
        {/* Tick marks — offset by LABEL_WIDTH so tick 0 aligns with clip area */}
        {ticks.map((tick) => (
          <div
            key={tick.time}
            className="absolute top-0"
            style={{ left: `${tick.time * pixelsPerSecond + LABEL_WIDTH}px` }}
          >
            <div
              className={`w-px bg-slate-700 ${tick.isMajor ? "h-full" : "h-1/2"}`}
            />
            {tick.isMajor && (
              <span className="absolute left-1 top-1 font-mono text-[10px] text-slate-500 whitespace-nowrap">
                {formatTime(tick.time)}
              </span>
            )}
          </div>
        ))}

        {/* Playhead — offset by LABEL_WIDTH */}
        <div
          className="absolute top-0 w-[2px] h-full bg-blue-500 z-20 pointer-events-none"
          style={{ left: `${playheadTime * pixelsPerSecond + LABEL_WIDTH}px` }}
        >
          {/* Triangle handle on top of the playhead */}
          <div
            className="absolute -top-0 -left-1.5 w-3 h-2 bg-blue-500"
            style={{ clipPath: "polygon(50% 100%, 0 0, 100% 0)" }}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────

/**
 * Determine the tick interval (in seconds) based on the current zoom level.
 *
 * - At high zoom (≥ 100 px/s): tick every 1 second
 * - At medium zoom (≥ 50 px/s): tick every 2 seconds
 * - At medium-low zoom (≥ 20 px/s): tick every 5 seconds
 * - At low zoom (< 20 px/s): tick every 10 seconds
 */
function getTickInterval(pps: number): number {
  if (pps >= 100) return 1
  if (pps >= 50) return 2
  if (pps >= 20) return 5
  return 10
}

/**
 * Format a time value in seconds to the `MM:SS` format.
 */
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
}
