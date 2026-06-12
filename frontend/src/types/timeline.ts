// ─── Canvas / export settings ──────────────────────────────────────

export interface TimelineCanvas {
  width: number   // default: 1920
  height: number  // default: 1080
  fps: number     // default: 30
}

// ─── Clip types ────────────────────────────────────────────────────

/** Camera / image movement effects — only valid for image clips */
export type ClipMovement =
  | "zoom_in"
  | "zoom_out"
  | "pan_left"
  | "pan_right"
  | "pan_up"
  | "pan_down"

/** What kind of media a clip references */
export type ClipSourceType = "image" | "audio" | "subtitle"

/** A single clip placed on a track */
export interface TimelineClip {
  id: string
  source_type: ClipSourceType
  /** Relative or absolute path to the source file */
  source_path: string
  /** Position on the timeline in seconds */
  start_time: number
  /** How long the clip plays in seconds */
  duration: number
  /** Trim start inside the source media (seconds) */
  trim_in: number
  /** Trim end inside the source media (seconds) */
  trim_out: number
  /** Ken Burns-style movement — only for image clips */
  movement?: ClipMovement
  /** Movement intensity, range 0.01-0.15, default 0.05 */
  intensity?: number
  /** Audio volume 0.0-1.0 — only for audio clips */
  volume?: number
  /** Displayed text content — only for subtitle clips */
  text?: string
}

// ─── Track types ───────────────────────────────────────────────────

export type TrackType = "video" | "audio" | "subtitle"

/** A single track that holds clips */
export interface Track {
  id: string
  type: TrackType
  name: string
  muted: boolean
  locked: boolean
  clips: TimelineClip[]
}

// ─── Timeline document ─────────────────────────────────────────────

/** The full timeline document — mirrors the backend timeline.json schema */
export interface Timeline {
  version: number
  canvas: TimelineCanvas
  /** Total duration in seconds */
  duration: number
  tracks: Track[]
}

// ─── Store state ───────────────────────────────────────────────────

export interface TimelineState {
  timeline: Timeline | null
  selectedClipId: string | null
  selectedTrackId: string | null
  /** Playhead position in seconds */
  playheadTime: number
  /** Zoom level: pixels per second (default 50 = 1s = 50px) */
  pixelsPerSecond: number
  isPlaying: boolean
  isLoading: boolean
  isSaving: boolean
  error: string | null
}

// ─── Store actions ─────────────────────────────────────────────────

export interface TimelineActions {
  /** Load a timeline from the backend by project id */
  loadTimeline: (projectId: string) => Promise<void>
  /** Persist the current timeline to the backend */
  saveTimeline: (projectId: string) => Promise<void>

  // Selection
  selectClip: (clipId: string | null) => void
  selectTrack: (trackId: string | null) => void

  // Clip mutations
  /** Merge a partial patch into an existing clip */
  updateClip: (clipId: string, patch: Partial<TimelineClip>) => void
  /** Split a clip on a track at the given time */
  splitClipAt: (trackId: string, timeSec: number) => void
  /** Trim a clip from the "in" or "out" edge by a delta in seconds */
  trimClip: (clipId: string, edge: "in" | "out", deltaSec: number) => void
  deleteClip: (clipId: string) => void
  reorderClip: (clipId: string, trackId: string, newIndex: number) => void

  // Playhead & zoom
  setPlayhead: (timeSec: number) => void
  setZoom: (pps: number) => void

  // Playback
  setPlaying: (playing: boolean) => void

  // Meta
  setError: (error: string | null) => void
  /** Reset the store to initial state */
  reset: () => void
}

// ─── Combined store ────────────────────────────────────────────────

export type TimelineStore = TimelineState & TimelineActions

// ─── API responses ─────────────────────────────────────────────────

export interface TimelineApiResponse {
  ok: boolean
  timeline?: Timeline
  message?: string
}

export interface ExportApiResponse {
  ok: boolean
  job_id?: string
  message?: string
}
