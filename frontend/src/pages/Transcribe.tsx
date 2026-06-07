import { useEffect, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import { Mic, Download, CheckCircle, AlertCircle, Play, FileAudio, FileText, FolderOpen } from "lucide-react"
import PageHeader from "../components/PageHeader"
import DropZone from "../components/DropZone"
import Card from "../components/Card"
import EmptyState from "../components/EmptyState"
import ProgressBar from "../components/ProgressBar"
import SRTPreview from "../components/SRTPreview"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"

interface SrtBlock {
  index: number
  start: string
  end: string
  text: string
}

interface MediaFile {
  filename: string
  path: string
  size_mb?: number
  size_kb?: number
  modified: number
  location: string
}

type JobStatus = "idle" | "uploaded" | "running" | "done" | "failed"

export default function Transcribe() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [textFile, setTextFile] = useState<File | null>(null)
  const [detectedAudio, setDetectedAudio] = useState<MediaFile | null>(null)
  const [detectedText, setDetectedText] = useState<MediaFile | null>(null)
  const [jobStatus, setJobStatus] = useState<JobStatus>("idle")
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState("")
  const [srtBlocks, setSrtBlocks] = useState<SrtBlock[]>([])
  const [wordCount, setWordCount] = useState(0)
  const [language, setLanguage] = useState("")
  const [projectTitle, setProjectTitle] = useState("")
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => {
      setProjectTitle(p.title || p.name)
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    api.getTranscription(projectId).then((res) => {
      if (res.has_transcription && res.srt) {
        setSrtBlocks(res.srt)
        setWordCount(res.word_count ?? 0)
        setLanguage(res.language ?? "")
        setJobStatus("done")
      }
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    api.getMediaInfo(projectId).then((res) => {
      if (res.has_audio && res.primary_audio) {
        setDetectedAudio(res.primary_audio)
      }
      if (res.has_text && res.primary_text) {
        setDetectedText(res.primary_text)
      }
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    return () => { wsRef.current?.close() }
  }, [])

  // Polling fallback when running (WebSocket might not deliver)
  useEffect(() => {
    if (jobStatus !== "running") return
    const interval = setInterval(async () => {
      try {
        const res = await api.getTranscription(projectId!)
        if (res.has_transcription && res.srt) {
          setSrtBlocks(res.srt)
          setWordCount(res.word_count ?? 0)
          setLanguage(res.language ?? "")
          setJobStatus("done")
          setProgress(100)
          setMessage("Complete")
          clearInterval(interval)
        }
      } catch {}
    }, 2000)
    return () => clearInterval(interval)
  }, [jobStatus, projectId])

  const connectWS = () => {
    if (!projectId) return
    wsRef.current?.close()
    const ws = new WebSocket(api.transcribeWsUrl(projectId))
    wsRef.current = ws

    ws.onopen = () => console.log("[Transcribe] WS connected")

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === "progress") {
        setProgress(data.progress * 100)
        setMessage(data.message)
        setJobStatus("running")
      } else if (data.type === "complete") {
        setJobStatus("done")
        setProgress(100)
        setMessage("Complete")
        if (data.result) {
          setWordCount(data.result.word_count ?? 0)
          setLanguage(data.result.language ?? "")
        }
        api.getTranscription(projectId).then((res) => {
          if (res.srt) setSrtBlocks(res.srt)
        })
        toast("Transcription complete!", "success")
      } else if (data.type === "error") {
        setJobStatus("failed")
        setMessage(data.message)
        toast(`Transcription failed: ${data.message}`, "error")
      }
    }

    ws.onerror = () => setJobStatus("failed")
  }

  const handleAudioUpload = async (files: File[]) => {
    if (!projectId || files.length === 0) return
    const audio = files[0]
    setAudioFile(audio)
    setJobStatus("idle")
    setProgress(0)
    setMessage("")

    try {
      await api.uploadAudio(projectId, audio, textFile ?? undefined)
      setJobStatus("uploaded")
      toast("Audio uploaded. Ready to transcribe.", "success")
    } catch (err: any) {
      setJobStatus("failed")
      setMessage(err?.message ?? "Upload failed")
      toast(err?.message ?? "Upload failed", "error")
    }
  }

  const handleStartTranscription = async () => {
    if (!projectId) return
    console.log("[Transcribe] Start clicked, projectId=" + projectId)

    connectWS()

    try {
      const res = await api.startTranscription(projectId)
      console.log("[Transcribe] Start response:", res)
      setJobStatus("running")
      setMessage("Starting transcription...")
    } catch (err: any) {
      console.log("[Transcribe] Start error:", err)
      setJobStatus("failed")
      setMessage(err?.message ?? "Failed to start transcription")
      toast(err?.message ?? "Failed to start transcription", "error")
    }
  }

  const handleTextUpload = (files: File[]) => {
    if (files.length > 0) setTextFile(files[0])
  }

  const handleDownload = (filename: string) => {
    if (!projectId) return
    window.open(`/api/projects/${projectId}/transcribe/download/${filename}`, "_blank")
  }

  const hasFilesReady = audioFile || detectedAudio

  if (!projectId) {
    return (
      <EmptyState
        icon={<Mic />}
        title="No project selected"
        description="Select a project from the Dashboard to transcribe audio"
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Transcription"}
        description="Upload audio and transcribe with Whisper"
        backTo={`/editor/${projectId}`}
        actions={
          jobStatus === "done" ? (
            <div className="flex items-center gap-2">
              <button className="btn-secondary" onClick={() => handleDownload("script.srt")}>
                <Download className="w-4 h-4" /> SRT
              </button>
              <button className="btn-secondary" onClick={() => handleDownload("script.json")}>
                <Download className="w-4 h-4" /> JSON
              </button>
            </div>
          ) : undefined
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2 space-y-4">
          {/* Detected Files */}
          {(detectedAudio || detectedText) && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <FolderOpen className="w-4 h-4 text-accent" />
                <h3 className="text-sm font-semibold text-white font-sans">Detected Files</h3>
              </div>
              
              {detectedAudio && (
                <div className="flex items-center gap-3 p-3 bg-surface-hover rounded-lg mb-2">
                  <FileAudio className="w-5 h-5 text-blue-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{detectedAudio.filename}</p>
                    <p className="text-xs text-gray-500">
                      {detectedAudio.size_mb?.toFixed(2)} MB • {detectedAudio.location}
                    </p>
                  </div>
                  <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />
                </div>
              )}

              {detectedText && (
                <div className="flex items-center gap-3 p-3 bg-surface-hover rounded-lg">
                  <FileText className="w-5 h-5 text-yellow-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{detectedText.filename}</p>
                    <p className="text-xs text-gray-500">
                      {detectedText.size_kb?.toFixed(2)} KB • {detectedText.location}
                    </p>
                  </div>
                  <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />
                </div>
              )}
            </Card>
          )}

          {/* Upload Section */}
          {!hasFilesReady && (
            <>
              <DropZone
                label="Drop audio file here"
                hint="Supports MP3, WAV, M4A — up to 1GB"
                accept="audio/*"
                onFiles={handleAudioUpload}
              />

              <DropZone
                label="Optional: reference text file"
                hint="TXT file for alignment (improves accuracy)"
                accept=".txt"
                onFiles={handleTextUpload}
              />
            </>
          )}

          {/* Uploaded File Info */}
          {audioFile && (
            <Card className="mt-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white">{audioFile.name}</p>
                  <p className="text-xs text-gray-500">{(audioFile.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
              </div>
            </Card>
          )}

          {/* Start Button */}
          {hasFilesReady && jobStatus !== "running" && jobStatus !== "done" && (
            <button
              className="btn-primary w-full flex items-center justify-center gap-2"
              onClick={handleStartTranscription}
            >
              <Play className="w-4 h-4" />
              Start Transcription
            </button>
          )}

          <Card>
            <h3 className="text-sm font-semibold text-white mb-3 font-sans">Job Status</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500 font-body">Status</span>
                <span className={`text-xs font-mono ${
                  jobStatus === "done" ? "text-green-400" :
                  jobStatus === "failed" ? "text-red-400" :
                  jobStatus === "running" ? "text-accent" :
                  jobStatus === "uploaded" ? "text-yellow-400" : "text-gray-400"
                }`}>
                  {jobStatus === "idle" && "Idle"}
                  {jobStatus === "uploaded" && "Ready to transcribe"}
                  {jobStatus === "running" && "Running..."}
                  {jobStatus === "done" && "Complete"}
                  {jobStatus === "failed" && "Failed"}
                </span>
              </div>

              {jobStatus === "running" && (
                <div className="space-y-2">
                  <ProgressBar progress={progress} />
                  <p className="text-xs text-gray-500 font-body">{message}</p>
                </div>
              )}

              {jobStatus === "done" && (
                <>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500 font-body">Language</span>
                    <span className="text-gray-300 font-mono text-xs">{language || "—"}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500 font-body">Words</span>
                    <span className="text-gray-300 font-mono text-xs">{wordCount}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500 font-body">Segments</span>
                    <span className="text-gray-300 font-mono text-xs">{srtBlocks.length}</span>
                  </div>
                </>
              )}

              {jobStatus === "failed" && (
                <div className="flex items-center gap-2 text-red-400 text-xs">
                  <AlertCircle className="w-4 h-4" />
                  <span>{message}</span>
                </div>
              )}
            </div>
          </Card>
        </div>

        <div className="lg:col-span-3">
          {(jobStatus === "idle" || jobStatus === "uploaded") && !hasFilesReady && (
            <EmptyState
              icon={<Mic />}
              title="No transcription yet"
              description="Upload an audio file or add files to the project folder"
            />
          )}

          {jobStatus === "idle" && hasFilesReady && (
            <EmptyState
              icon={<Mic />}
              title="Ready to transcribe"
              description="Click 'Start Transcription' to begin"
            />
          )}

          {jobStatus === "done" && srtBlocks.length > 0 && (
            <SRTPreview blocks={srtBlocks} />
          )}

          {jobStatus === "done" && srtBlocks.length === 0 && (
            <EmptyState
              icon={<CheckCircle />}
              title="Transcription complete"
              description="No segments found in audio"
            />
          )}
        </div>
      </div>
    </div>
  )
}
