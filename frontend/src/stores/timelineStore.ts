import { create } from "zustand"
import { api } from "../api/client"
import type {
  Timeline,
  Track,
  TimelineClip,
  TimelineStore,
} from "../types/timeline"

// ─── Initial state ─────────────────────────────────────────────────

const initialState: Pick<
  TimelineStore,
  | "timeline"
  | "selectedClipId"
  | "selectedTrackId"
  | "playheadTime"
  | "pixelsPerSecond"
  | "isPlaying"
  | "isLoading"
  | "isSaving"
  | "error"
> = {
  timeline: null,
  selectedClipId: null,
  selectedTrackId: null,
  playheadTime: 0,
  pixelsPerSecond: 50,
  isPlaying: false,
  isLoading: false,
  isSaving: false,
  error: null,
}

// ─── Helpers ───────────────────────────────────────────────────────

/** Find the furthest point across all clips to determine total duration */
function recalculateDuration(timeline: Timeline): number {
  let maxEnd = 0
  for (const track of timeline.tracks) {
    for (const clip of track.clips) {
      const end = clip.start_time + clip.duration
      if (end > maxEnd) maxEnd = end
    }
  }
  return maxEnd
}

/** Locate a clip by id across all tracks — returns the track reference, index and clip */
function findClipById(
  timeline: Timeline,
  clipId: string,
): { track: Track; clipIndex: number; clip: TimelineClip } | null {
  for (const track of timeline.tracks) {
    const clipIndex = track.clips.findIndex((c) => c.id === clipId)
    if (clipIndex !== -1) {
      return { track, clipIndex, clip: track.clips[clipIndex] }
    }
  }
  return null
}

// ─── Store ─────────────────────────────────────────────────────────

export const useTimelineStore = create<TimelineStore>((set, get) => ({
  ...initialState,

  // ── Lifecycle ──────────────────────────────────────────────────

  loadTimeline: async (projectId) => {
    set({ isLoading: true, error: null })
    try {
      const res = await api.getTimeline(projectId)
      if (res.ok && res.timeline) {
        set({ timeline: res.timeline, isLoading: false })
      } else {
        set({
          error: res.message || "Failed to load timeline",
          isLoading: false,
        })
      }
    } catch (e) {
      set({ error: String(e), isLoading: false })
    }
  },

  saveTimeline: async (projectId) => {
    const { timeline } = get()
    if (!timeline) return

    set({ isSaving: true })
    try {
      const res = await api.saveTimeline(projectId, timeline)
      if (!res.ok) {
        set({ error: res.message || "Failed to save timeline" })
      }
    } catch (e) {
      set({ error: String(e) })
    } finally {
      set({ isSaving: false })
    }
  },

  // ── Selection ──────────────────────────────────────────────────

  selectClip: (clipId) => set({ selectedClipId: clipId }),

  selectTrack: (trackId) => set({ selectedTrackId: trackId }),

  // ── Clip mutations ─────────────────────────────────────────────

  updateClip: (clipId, patch) => {
    const { timeline } = get()
    if (!timeline) return

    // Minimum duration guard: clamp duration to at least 0.5s
    const safePatch =
      typeof patch.duration === "number" && patch.duration < 0.5
        ? { ...patch, duration: 0.5 }
        : patch

    const newTimeline: Timeline = {
      ...timeline,
      tracks: timeline.tracks.map((track) => ({
        ...track,
        clips: track.clips.map((clip) =>
          clip.id === clipId ? { ...clip, ...safePatch } : clip,
        ),
      })),
    }
    newTimeline.duration = recalculateDuration(newTimeline)

    set({ timeline: newTimeline })
  },

  splitClipAt: (trackId, timeSec) => {
    const { timeline } = get()
    if (!timeline) return

    const trackIndex = timeline.tracks.findIndex((t) => t.id === trackId)
    if (trackIndex === -1) return

    const track = timeline.tracks[trackIndex]
    const clipIndex = track.clips.findIndex(
      (c) => c.start_time <= timeSec && timeSec < c.start_time + c.duration,
    )
    if (clipIndex === -1) return

    const original = track.clips[clipIndex]

    // Guard 1: can't split at exact start or exact end of clip
    if (timeSec <= original.start_time || timeSec >= original.start_time + original.duration) {
      return
    }

    const splitPoint = timeSec - original.start_time

    // Guard 2: both resulting clips must be at least 0.5s
    if (splitPoint < 0.5 || original.duration - splitPoint < 0.5) {
      return
    }

    const clipA: TimelineClip = {
      ...original,
      id: `${original.id}_a`,
      duration: splitPoint,
      trim_out: original.trim_in + splitPoint,
    }

    const clipB: TimelineClip = {
      ...original,
      id: `${original.id}_b`,
      start_time: timeSec,
      duration: original.duration - splitPoint,
      trim_in: original.trim_in + splitPoint,
    }

    const newClips = [...track.clips]
    newClips.splice(clipIndex, 1, clipA, clipB)

    const newTimeline: Timeline = {
      ...timeline,
      tracks: timeline.tracks.map((t, i) =>
        i === trackIndex ? { ...t, clips: newClips } : t,
      ),
    }
    newTimeline.duration = recalculateDuration(newTimeline)

    set({ timeline: newTimeline })
  },

  trimClip: (clipId, edge, deltaSec) => {
    const { timeline } = get()
    if (!timeline) return

    const found = findClipById(timeline, clipId)
    if (!found) return

    const { track, clipIndex, clip } = found
    const MIN_DURATION = 0.5

    let newTrimIn = clip.trim_in ?? 0
    let newTrimOut = clip.trim_out ?? clip.duration ?? 0

    if (edge === "in") {
      newTrimIn = Math.max(0, (clip.trim_in ?? 0) + deltaSec)
    } else {
      newTrimOut = (clip.trim_out ?? clip.duration ?? 0) + deltaSec
    }

    const newDuration = newTrimOut - newTrimIn

    // Minimum duration guard: clip must be at least 0.5s
    if (newDuration < MIN_DURATION || !isFinite(newDuration)) return

    // Overlap prevention: when extending duration, don't overlap the next clip
    if (newDuration > (clip.duration ?? 0)) {
      const nextClip = track.clips[clipIndex + 1]
      if (nextClip) {
        const proposedEnd = clip.start_time + newDuration
        if (proposedEnd > nextClip.start_time) return
      }
    }

    const newTimeline: Timeline = {
      ...timeline,
      tracks: timeline.tracks.map((track) => ({
        ...track,
        clips: track.clips.map((c) =>
          c.id === clipId
            ? { ...c, trim_in: newTrimIn, trim_out: newTrimOut, duration: newDuration }
            : c,
        ),
      })),
    }
    newTimeline.duration = recalculateDuration(newTimeline)

    set({ timeline: newTimeline })
  },

  deleteClip: (clipId) => {
    const { timeline, selectedClipId } = get()
    if (!timeline) return

    const newTimeline: Timeline = {
      ...timeline,
      tracks: timeline.tracks.map((track) => ({
        ...track,
        clips: track.clips.filter((c) => c.id !== clipId),
      })),
    }
    newTimeline.duration = recalculateDuration(newTimeline)

    set({
      timeline: newTimeline,
      selectedClipId: selectedClipId === clipId ? null : selectedClipId,
    })
  },

  // ── Playhead & zoom ────────────────────────────────────────────

  setPlayhead: (timeSec) => {
    const { timeline } = get()
    const max = timeline?.duration ?? 0
    set({ playheadTime: Math.max(0, Math.min(timeSec, max)) })
  },

  setZoom: (pps) => {
    set({ pixelsPerSecond: Math.max(10, Math.min(pps, 200)) })
  },

  // ── Playback ───────────────────────────────────────────────────

  setPlaying: (playing) => set({ isPlaying: playing }),

  // ── Meta ───────────────────────────────────────────────────────

  setError: (error) => set({ error }),

  reset: () => set({ ...initialState }),
}))
