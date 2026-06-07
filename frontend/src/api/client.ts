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

  generateImages: (projectId: string, config?: { concurrency?: number; accounts?: string[] }) =>
    request<{ batch_id: string; total: number }>(
      `/api/projects/${projectId}/images/generate`,
      { method: "POST", body: JSON.stringify(config || {}) },
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

  startTranscription: (projectId: string) =>
    request<{ job_id: string; status: string }>(
      `/api/projects/${projectId}/transcribe/start`,
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
}
