const BASE = ""

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }))
    throw new Error(err.detail ?? err.message)
  }
  return res.json()
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),

  // Setup
  setupStatus: () =>
    request<{ has_channels: boolean; suggested_base: string }>("/api/setup/status"),

  // Channels
  listChannels: () =>
    request<{ channels: import("../types").Channel[] }>("/api/channels"),

  createChannel: (data: { name: string; base_path: string }) =>
    request<import("../types").Channel>("/api/channels", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteChannel: (id: string) =>
    request<{ channel_id: string }>(`/api/channels/${id}`, { method: "DELETE" }),

  // Projects
  listProjects: (channelId?: string) => {
    const qs = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ""
    return request<{ projects: import("../types").ProjectRow[] }>(`/api/projects${qs}`)
  },

  createProject: (data: { name: string; title?: string; channel_id?: string }) =>
    request<import("../types").ProjectMetadata>("/api/projects", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getProject: (id: string) =>
    request<import("../types").ProjectMetadata>(`/api/projects/${id}`),

  deleteProject: (id: string) =>
    request<{ project_id: string }>(`/api/projects/${id}`, { method: "DELETE" }),

  // Fragments
  listFragments: (projectId: string) =>
    request<{ fragments: import("../types").Fragment[] }>(
      `/api/projects/${projectId}/fragments`
    ),

  updateFragment: (projectId: string, fragmentId: number, data: Partial<import("../types").Fragment>) =>
    request<{ project_id: string; fragment_id: number }>(
      `/api/projects/${projectId}/fragments/${fragmentId}`,
      { method: "PUT", body: JSON.stringify(data) }
    ),

  // Images
  listImages: (projectId: string) =>
    request<{ images: import("../types").ImageInfo[] }>(
      `/api/projects/${projectId}/images`
    ),

  listAccounts: () =>
    request<{ accounts: Array<{ hash: string; email: string; connected: boolean }> }>(
      `/api/accounts`
    ),

  generateImages: (projectId: string, config?: { concurrency?: number; accounts?: string[]; reference_image_ids?: string[]; model?: string; fragment_ids?: number[]; force?: boolean }) =>
    request<{ batch_id: string; total: number; reference_image_ids: string[] }>(
      `/api/projects/${projectId}/images/generate`,
      { method: "POST", body: JSON.stringify(config || {}) },
    ),

  // Reference Images
  uploadReference: (projectId: string, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<{ ok: boolean; filename: string; size_kb: number }>(
      `/api/projects/${projectId}/images/reference`,
      { method: "POST", body: form, headers: {} },
    )
  },

  listReferences: (projectId: string) =>
    request<{ references: Array<{ name: string; url: string; size_kb: number }> }>(
      `/api/projects/${projectId}/images/reference`,
    ),

  deleteReference: (projectId: string, filename: string) =>
    request<{ ok: boolean; deleted: string }>(
      `/api/projects/${projectId}/images/reference/${encodeURIComponent(filename)}`,
      { method: "DELETE" },
    ),

  imageEventsUrl: (projectId: string) => `/api/projects/${projectId}/images/events`,

  // Transcription
  getMediaInfo: (projectId: string) =>
    request<{
      has_audio: boolean
      audio_files?: Array<{
        filename: string
        path: string
        size_mb: number
        modified: number
        location: string
      }>
      primary_audio?: {
        filename: string
        path: string
        size_mb: number
        modified: number
        location: string
      }
      has_text: boolean
      text_files?: Array<{
        filename: string
        path: string
        size_kb: number
        modified: number
        location: string
      }>
      primary_text?: {
        filename: string
        path: string
        size_kb: number
        modified: number
        location: string
      }
    }>(`/api/projects/${projectId}/transcribe/media`),

  uploadAudio: (projectId: string, audio: File, text?: File) => {
    const form = new FormData()
    form.append("audio", audio)
    if (text) form.append("text", text)
    return request<{ status: string; audio_file: string; audio_path: string; has_reference_text: boolean }>(
      `/api/projects/${projectId}/transcribe/upload`,
      { method: "POST", body: form, headers: {} },
    )
  },

  startTranscription: (projectId: string, modelSize?: string) =>
    request<{ job_id: string; status: string; model_size: string }>(
      `/api/projects/${projectId}/transcribe/start${modelSize ? `?model_size=${modelSize}` : ""}`,
      { method: "POST" },
    ),

  transcribeAudio: (projectId: string, audio: File, text?: File) => {
    const form = new FormData()
    form.append("audio", audio)
    if (text) form.append("text", text)
    return request<{ job_id: string; status: string }>(
      `/api/projects/${projectId}/transcribe`,
      { method: "POST", body: form, headers: {} },
    )
  },

  getTranscription: (projectId: string) =>
    request<{
      has_transcription: boolean
      language?: string
      word_count?: number
      segment_count?: number
      srt?: { index: number; start: string; end: string; text: string }[]
    }>(`/api/projects/${projectId}/transcribe`),

  transcribeWsUrl: (projectId: string) => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
    return `${proto}//${window.location.host}/api/projects/${projectId}/transcribe/ws`
  },

  // Word timestamps for script selection
  getWordTimestamps: (projectId: string) =>
    request<{ words: Array<{ text: string; start: number; end: number; type: string }>; total: number }>(
      `/api/projects/${projectId}/transcribe/words`,
    ),

  // Render
  startRender: (projectId: string, config?: {
    filter_mode?: "all" | "even" | "odd"
    width?: number
    height?: number
    fps?: number
    intensity?: number
    seed?: number
    subtitles?: boolean
  }) =>
    request<{ job_id: string; status: string }>(
      `/api/projects/${projectId}/render`,
      { method: "POST", body: JSON.stringify(config || {}) },
    ),

  getRenderStatus: (projectId: string) =>
    request<{
      has_render: boolean
      output_path?: string
      file_size?: number
      file_size_mb?: number
    }>(`/api/projects/${projectId}/render`),

  deleteRender: (projectId: string) =>
    request<{ ok: boolean; deleted: string | null }>(
      `/api/projects/${projectId}/render`,
      { method: "DELETE" },
    ),

  renderWsUrl: (projectId: string) => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
    return `${proto}//${window.location.host}/api/projects/${projectId}/render/ws`
  },

  renderDownloadUrl: (projectId: string) =>
    `/api/projects/${projectId}/render/download`,

  // Workflow (Orchestrator)
  startWorkflow: (projectId: string, config?: {
    render?: {
      filter_mode?: "all" | "even" | "odd"
      width?: number
      height?: number
      fps?: number
      intensity?: number
      seed?: number
      subtitles?: boolean
    }
  }) =>
    request<{ project_id: string; status: string }>(
      `/api/projects/${projectId}/workflow`,
      { method: "POST", body: JSON.stringify(config || {}) },
    ),

  getWorkflowStatus: (projectId: string) =>
    request<{
      project_id: string
      status: string
      current_stage: string | null
      stages: Record<string, { status: string; progress: number }>
      error: string | null
      started_at: string | null
      completed_at: string | null
      results: Record<string, unknown>
      stage_timings: Record<string, any>
    }>(`/api/projects/${projectId}/workflow`),

  cancelWorkflow: (projectId: string) =>
    request<{ project_id: string; status: string }>(
      `/api/projects/${projectId}/workflow/cancel`,
      { method: "POST" },
    ),

  workflowEventsUrl: (projectId: string) =>
    `/api/projects/${projectId}/workflow/events`,

  // Shorts
  analyzeShorts: (projectId: string) =>
    request<{
      suggestions: Array<{
        index: number
        start_sec: number
        end_sec: number
        duration: number
        score: number
        reason: string
        text_preview: string
      }>
    }>(`/api/projects/${projectId}/shorts/analyze`, { method: "POST" }),

  renderShorts: (projectId: string, data: { selections: number[]; font_size?: number; with_subtitles?: boolean; manual_clips?: Array<{index: number; start_sec: number; end_sec: number; duration: number; reason: string; text_preview: string}> }) =>
    request<{
      results: Array<{
        index: number
        filename: string
        success: boolean
        error?: string | null
      }>
    }>(`/api/projects/${projectId}/shorts/render`, { method: "POST", body: JSON.stringify(data) }),

  listShorts: (projectId: string) =>
    request<{
      files: Array<{ filename: string; size_bytes: number }>
    }>(`/api/projects/${projectId}/shorts/downloads`),

  shortsDownloadUrl: (projectId: string, filename: string) =>
    `/api/projects/${projectId}/shorts/file/${filename}`,

  // Script (full guion text)
  getScript: (projectId: string) =>
    request<{ text: string; project_id: string }>(
      `/api/projects/${projectId}/script`,
    ),

  saveScript: (projectId: string, text: string) =>
    request<{ project_id: string; path: string; saved: boolean }>(
      `/api/projects/${projectId}/script`,
      { method: "PUT", body: JSON.stringify({ text }) },
    ),

  fragmentScript: (projectId: string, text: string) =>
    request<{ project_id: string; total: number; fragments: import("../types").Fragment[] }>(
      `/api/projects/${projectId}/script/fragment`,
      { method: "POST", body: JSON.stringify({ text }) },
    ),

  // Prompt Generation
  generatePrompts: (projectId: string, style?: string, useGeminiWeb?: boolean, fragmentIds?: number[]) =>
    request<{ project_id: string; total: number; results: Array<{ fragment_id: number; original_text: string; image_prompt: string }> }>(
      `/api/projects/${projectId}/prompts/generate`,
      { method: "POST", body: JSON.stringify({ style: style || "Cinematico", use_gemini_web: useGeminiWeb ?? true, ...(fragmentIds?.length ? { fragment_ids: fragmentIds } : {}) }) },
    ),

  setPromptStyle: (projectId: string, style: string) =>
    request<{ project_id: string; style: string; saved: boolean }>(
      `/api/projects/${projectId}/prompts/style`,
      { method: "PUT", body: JSON.stringify({ style }) },
    ),

  promptEventsUrl: (projectId: string) => {
    return `/api/projects/${projectId}/prompts/events`
  },

  // Gemini Web Bridge
  getGeminiBridgeStatus: () =>
    request<{
      ok: boolean
      total_profiles: number
      authenticated: number
      profiles: Array<{
        profile_id: string
        profile_label: string
        has_psid: boolean
        has_active_tab: boolean
        updated_at: string
        auth_status: string
      }>
      selected: { profile_id: string | null; profile_label: string | null } | null
    }>("/api/bridge/gemini/status"),

  // Timeline
  getTimeline: (projectId: string) =>
    request<{ ok: boolean; timeline?: import("../types/timeline").Timeline; message?: string }>(
      `/api/projects/${projectId}/timeline`,
    ),

  saveTimeline: (projectId: string, timeline: import("../types/timeline").Timeline) =>
    request<{ ok: boolean; message?: string }>(
      `/api/projects/${projectId}/timeline`,
      { method: "PUT", body: JSON.stringify(timeline) },
    ),

  exportTimeline: (projectId: string) =>
    request<{ ok: boolean; message?: string; output?: string }>(
      `/api/projects/${projectId}/timeline/export`,
      { method: "POST" },
    ),

  /** Connect to SSE stream for timeline export progress events.
   *  Backend event names:
   *    - timeline_export_progress → { progress: number, message: string }
   *    - timeline_export_complete → { output: string }
   *    - timeline_export_error   → { message: string }
   *  Returns the EventSource so the caller can close it. */
  connectExportSSE: (
    projectId: string,
    handlers: {
      onProgress?: (progress: number, message: string) => void
      onComplete?: (output: string) => void
      onError?: (message: string) => void
    },
  ) => {
    const es = new EventSource(`/api/projects/${projectId}/stream`)

    es.addEventListener("timeline_export_progress", (e: MessageEvent) => {
      const data = JSON.parse(e.data)
      handlers.onProgress?.(data.progress, data.message)
    })

    es.addEventListener("timeline_export_complete", (e: MessageEvent) => {
      const data = JSON.parse(e.data)
      handlers.onComplete?.(data.output)
      es.close()
    })

    es.addEventListener("timeline_export_error", (e: MessageEvent) => {
      const data = JSON.parse(e.data)
      handlers.onError?.(data.message)
      es.close()
    })

    // Safety: auto-close after 5 minutes
    setTimeout(() => es.close(), 300000)

    return es
  },

  // Gems
  listGems: () =>
    request<{
      gems: Array<{ name: string; type: string; preview: string }>
      total: number
    }>("/api/gems"),

  getGem: (name: string) =>
    request<{ name: string; type: string; value: string }>(`/api/gems/${encodeURIComponent(name)}`),

  updateGem: (name: string, data: { name?: string; type?: string; value?: string }) =>
    request<{ ok: boolean; name: string }>(`/api/gems/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Orphaned project scanner
  scanOrphans: () =>
    request<{
      orphans: Array<{
        id: string
        title: string
        channel_id: string
        channel_name: string
        path: string
        created: string
        has_video: boolean
        has_audio: boolean
        has_images: boolean
      }>
    }>("/api/projects/scan", { method: "POST" }),

  importOrphan: (projectId: string, channelId: string) =>
    request<{ project_id: string; imported: boolean }>("/api/projects/import", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, channel_id: channelId }),
    }),
}
