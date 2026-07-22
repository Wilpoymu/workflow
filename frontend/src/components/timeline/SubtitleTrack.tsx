import type { Track } from "../../types/timeline"

// ─── Props ──────────────────────────────────────────────────────────

interface SubtitleTrackProps {
  track: Track
  pixelsPerSecond: number
}

// ─── Component ──────────────────────────────────────────────────────

/**
 * Subtitle (SRT) track visualization.
 *
 * Phase 1: read-only display of subtitle blocks. If no clips exist,
 * shows a placeholder message. The actual SRT parsing and clip
 * population happens on the backend.
 *
 * The track is locked (non-interactive) — no selection or trim.
 */
export default function SubtitleTrack({ track, pixelsPerSecond: pps }: SubtitleTrackProps) {
  // ── Empty track placeholder ─────────────────────────────────────
  if (track.clips.length === 0) {
    return (
      <div className="relative h-16 bg-slate-950/50 border-b border-slate-800/50 flex items-center justify-center">
        <p className="text-[10px] text-slate-500 italic flex items-center gap-1.5">
          <svg className="w-3 h-3 text-amber-500/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
          </svg>
          Subtitles ready &mdash; will be burned during export (read-only in Phase 1)
        </p>
      </div>
    )
  }

  // ── Render subtitle blocks ──────────────────────────────────────
  return (
    <div className="relative h-16 bg-slate-950/50 border-b border-slate-800/50">
      {track.clips.map((clip) => (
        <div
          key={clip.id}
          className="absolute top-2 bottom-2 rounded bg-amber-600/20 border border-amber-600/30 px-2 flex items-center overflow-hidden"
          style={{
            left: `${clip.start_time * pps}px`,
            width: `${Math.max(clip.duration * pps, 20)}px`,
          }}
        >
          <span className="text-[10px] text-amber-300/70 truncate">
            {clip.text ?? clip.id}
          </span>
        </div>
      ))}
    </div>
  )
}
