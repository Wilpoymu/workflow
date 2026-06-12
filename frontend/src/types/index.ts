export interface Channel {
  id: string
  name: string
  base_path: string
  created_at: string
  updated_at: string
}

export interface ProjectRow {
  id: string
  name: string
  path: string
  created_at: string
  updated_at: string
  status: string
  channel_id?: string
}

export interface ProjectMetadata {
  name: string
  title: string
  created: string
  status: string
  base_dir: string
  files: {
    prompts: string
    audio: string
    images_dir: string
    thumbnail: string
    video: string
  }
  stats: {
    prompts_total: number
    images_generated: number
    images_failed: number
  }
  history: Array<{
    batch_id: string
    total: number
    done: number
    failed: number
    model: string
    accounts: string[]
    concurrency: number
    timestamp: string
  }>
  prompt_style?: string
}

export interface Fragment {
  fragment_id: number
  original_text: string
  image_prompt: string
  source: string
  status: string
  provider: string
  model: string
  updatedAt: string
}

export interface WhisperWord {
  text: string
  start: number
  end: number
  type: "word" | "spacing"
  speaker_id: string
  logprob: number
}

export interface SrtBlock {
  index: number
  start: string
  end: string
  text: string
}

export interface ImageInfo {
  fragment_id: number
  url: string
  status: string
  error?: string
}

export interface JobStatus {
  id: string
  project_id: string
  type: "transcribe" | "render" | "generate_images"
  status: "queued" | "running" | "done" | "failed"
  progress: number
  created_at: string
  started_at?: string
}
