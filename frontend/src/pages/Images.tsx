import { useEffect, useRef, useState, useCallback } from "react"
import { useParams } from "react-router-dom"
import { Image as ImageIcon, Sparkles, RefreshCw, Loader2, Users, Zap, CheckCircle, XCircle, Upload, Trash2 } from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import Badge from "../components/Badge"
import EmptyState from "../components/EmptyState"
import ProgressBar from "../components/ProgressBar"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type { ImageInfo } from "../types"

interface Account {
  hash: string
  email: string
  connected: boolean
}

export default function Images() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const storageKey = projectId ? `images-${projectId}` : null

  const [images, setImages] = useState<ImageInfo[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(() => {
    if (!storageKey) return new Set()
    const saved = sessionStorage.getItem(`${storageKey}-accounts`)
    return saved ? new Set(JSON.parse(saved)) : new Set()
  })
  const [concurrency, setConcurrency] = useState<number>(() => {
    if (!storageKey) return 2
    const saved = sessionStorage.getItem(`${storageKey}-concurrency`)
    return saved ? Number(saved) : 2
  })
  const [loading, setLoading] = useState(true)
  const [projectTitle, setProjectTitle] = useState("")
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState<Record<number, number>>({})
  const [batchId, setBatchId] = useState<string | null>(null)
  const [stats, setStats] = useState({ done: 0, failed: 0, total: 0 })
  const esRef = useRef<EventSource | null>(null)

  // Reference images
  const [references, setReferences] = useState<Array<{ name: string; url: string; size_kb: number }>>([])
  const [refUploading, setRefUploading] = useState(false)

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => {
      setProjectTitle(p.title || p.name)
    }).catch(() => {})
  }, [projectId])

  const loadImages = useCallback(async () => {
    if (!projectId) return
    try {
      const res = await api.listImages(projectId)
      setImages(res.images)
    } catch {
      toast("Failed to load images", "error")
    } finally {
      setLoading(false)
    }
  }, [projectId, toast])

  const loadReferences = useCallback(async () => {
    if (!projectId) return
    try {
      const res = await api.listReferences(projectId)
      setReferences(res.references)
    } catch { /* may not exist yet */ }
  }, [projectId])

  const loadAccounts = useCallback(async () => {
    try {
      const res = await api.listAccounts()
      setAccounts(res.accounts)
    } catch {
      // Accounts endpoint might not exist yet
    }
  }, [])

  useEffect(() => {
    if (!storageKey) return
    sessionStorage.setItem(`${storageKey}-concurrency`, String(concurrency))
  }, [concurrency, storageKey])

  useEffect(() => {
    if (!storageKey) return
    sessionStorage.setItem(`${storageKey}-accounts`, JSON.stringify([...selectedAccounts]))
  }, [selectedAccounts, storageKey])

  useEffect(() => {
    loadImages()
    loadAccounts()
    loadReferences()
    // Poll accounts every 5 seconds
    const interval = setInterval(loadAccounts, 5000)
    return () => {
      clearInterval(interval)
      esRef.current?.close()
    }
  }, [loadImages, loadAccounts, loadReferences])

  const subscribeSSE = () => {
    if (!projectId) return
    esRef.current?.close()
    const es = new EventSource(api.imageEventsUrl(projectId))
    esRef.current = es

    es.addEventListener("item_result", (e) => {
      const data = JSON.parse(e.data)
      setImages((prev) =>
        prev.map((img) =>
          img.fragment_id === data.fragmentId
            ? { ...img, status: data.status, url: data.url || img.url }
            : img,
        ),
      )
      setStats((prev) => ({
        ...prev,
        done: data.status === "done" ? prev.done + 1 : prev.done,
        failed: data.status === "failed" ? prev.failed + 1 : prev.failed,
      }))
    })

    es.addEventListener("progress", (e) => {
      const data = JSON.parse(e.data)
      setProgress((prev) => ({ ...prev, [data.fragmentId]: data.progress }))
    })

    es.addEventListener("complete", () => {
      setGenerating(false)
      setProgress({})
      setBatchId(null)
      loadImages()
      toast("Image generation complete", "success")
      es.close()
    })

    es.addEventListener("error", () => {
      setGenerating(false)
    })
  }

  const handleGenerate = async () => {
    if (!projectId) return
    if (selectedAccounts.size === 0) {
      toast("Select at least one account", "error")
      return
    }

    setGenerating(true)
    setProgress({})
    setStats({ done: 0, failed: 0, total: images.filter(i => i.status === "pending" || i.status === "failed").length })

    try {
      const res = await api.generateImages(projectId, {
        concurrency,
        accounts: Array.from(selectedAccounts),
      })
      setBatchId(res.batch_id)
      setStats(prev => ({ ...prev, total: res.total }))
      setImages((prev) =>
        prev.map((img) =>
          img.status === "pending" || img.status === "failed"
            ? { ...img, status: "generating" }
            : img,
        ),
      )
      subscribeSSE()
      toast(`Generating ${res.total} images across ${selectedAccounts.size} account${selectedAccounts.size > 1 ? "s" : ""} (${concurrency} per account)...`, "info")
    } catch (err: any) {
      setGenerating(false)
      toast(err?.message ?? "Failed to start generation", "error")
    }
  }

  const toggleAccount = (hash: string) => {
    setSelectedAccounts((prev) => {
      const next = new Set(prev)
      if (next.has(hash)) {
        next.delete(hash)
      } else {
        next.add(hash)
      }
      return next
    })
  }

  const connectedAccounts = accounts.filter(a => a.connected)
  const pendingCount = images.filter(i => i.status === "pending").length
  const failedCount = images.filter(i => i.status === "failed").length
  const doneCount = images.filter(i => i.status === "done").length
  const generatingCount = images.filter(i => i.status === "generating").length

  if (!projectId) {
    return (
      <EmptyState
        icon={<ImageIcon />}
        title="No project selected"
        description="Select a project from the Dashboard to generate images"
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Image Generation"}
        description="Generate scene images from your prompts using Flow accounts"
        backTo={`/editor/${projectId}`}
        actions={
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={generating || (pendingCount + failedCount) === 0}
          >
            {generating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {generating ? `Generating... (${stats.done + stats.failed}/${stats.total})` : "Generate All"}
          </button>
        }
      />

      {/* Accounts Section */}
      <Card className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-accent" />
            <h3 className="text-sm font-semibold text-white font-sans">
              Connected Accounts
            </h3>
            <Badge variant={connectedAccounts.length > 0 ? "success" : "default"}>
              {`${connectedAccounts.length} connected`}
            </Badge>
          </div>
          <button
            className="text-xs text-gray-500 hover:text-accent flex items-center gap-1"
            onClick={loadAccounts}
          >
            <RefreshCw className="w-3 h-3" />
            Refresh
          </button>
        </div>

        {connectedAccounts.length === 0 ? (
          <div className="text-center py-4 text-gray-500 text-sm">
            No accounts connected. Open the Chrome extension on Flow to connect.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {connectedAccounts.map((account) => (
              <label
                key={account.hash}
                className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                  selectedAccounts.has(account.hash)
                    ? "border-accent bg-accent/5"
                    : "border-border hover:border-accent/30"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedAccounts.has(account.hash)}
                  onChange={() => toggleAccount(account.hash)}
                  className="w-4 h-4 rounded border-border text-accent focus:ring-accent"
                />
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center text-white text-sm font-bold">
                  {account.email[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white truncate">{account.email}</p>
                  <p className="text-xs text-gray-500 font-mono">{account.hash.slice(0, 12)}...</p>
                </div>
                <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              </label>
            ))}
          </div>
        )}

        {/* Concurrency Slider */}
        {connectedAccounts.length > 0 && (
          <div className="mt-4 pt-4 border-t border-border">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-accent" />
                <span className="text-sm text-gray-400">Prompts per account:</span>
              </div>
              <input
                type="range"
                min="1"
                max="10"
                value={concurrency.toString()}
                onChange={(e) => setConcurrency(parseInt(e.target.value))}
                className="flex-1 h-2 bg-surface-hover rounded-lg appearance-none cursor-pointer"
                style={{ accentColor: "#2dd4bf" }}
              />
              <span className="text-sm font-mono text-white w-8 text-center">
                {concurrency}
              </span>
            </div>
            <p className="text-xs text-gray-600 mt-2">
              {connectedAccounts.length} account{connectedAccounts.length > 1 ? "s" : ""} × {concurrency} prompts each = up to {connectedAccounts.length * concurrency} total in parallel
            </p>
          </div>
        )}
      </Card>

      {/* Reference Image Section */}
      <Card className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Upload className="w-4 h-4 text-pink-400" />
            <h3 className="text-sm font-semibold text-white font-sans">
              Character Reference
            </h3>
          </div>
          <input
            type="file"
            id="refUpload"
            accept=".png,.jpg,.jpeg,.webp"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0]
              if (!file || !projectId) return
              if (file.size > 5 * 1024 * 1024) {
                toast("Image exceeds 5MB", "error")
                return
              }
              setRefUploading(true)
              try {
                const res = await api.uploadReference(projectId, file)
                toast(`Reference uploaded (${res.size_kb} KB)`, "success")
                loadReferences()
              } catch (err: any) {
                toast(err?.message ?? "Upload failed", "error")
              }
              setRefUploading(false)
            }}
          />
          <button
            className="btn-secondary text-xs"
            onClick={() => document.getElementById("refUpload")?.click()}
            disabled={refUploading}
          >
            {refUploading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Upload className="w-3 h-3" />
            )}
            {refUploading ? "Uploading..." : "Upload Reference"}
          </button>
        </div>

        {references.length === 0 ? (
          <p className="text-xs text-gray-600">
            No reference image set. Upload a character image to maintain visual consistency across all scenes.
          </p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {references.map((ref) => (
              <div key={ref.name} className="relative group">
                <div className="aspect-square rounded-lg overflow-hidden border border-border bg-surface-elevated">
                  <img
                    src={ref.url}
                    alt={ref.name}
                    className="w-full h-full object-cover"
                  />
                </div>
                <button
                  className="absolute top-1 right-1 p-1 rounded bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity text-red-400 hover:text-red-300"
                  onClick={async () => {
                    if (!projectId) return
                    try {
                      await api.deleteReference(projectId, ref.name)
                      loadReferences()
                      toast("Reference removed", "success")
                    } catch {
                      toast("Failed to delete reference", "error")
                    }
                  }}
                  title="Remove reference"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
                <p className="text-[10px] text-gray-600 truncate mt-1 text-center">
                  {ref.name} 
                  <span className="text-gray-700"> ({ref.size_kb} KB)</span>
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Stats Bar */}
      <div className="flex items-center gap-4 mb-4 text-sm">
        <span className="text-gray-500">
          Done: <span className="text-green-400 font-medium">{doneCount}</span>
        </span>
        <span className="text-gray-500">
          Generating: <span className="text-accent font-medium">{generatingCount}</span>
        </span>
        <span className="text-gray-500">
          Pending: <span className="text-yellow-400 font-medium">{pendingCount}</span>
        </span>
        <span className="text-gray-500">
          Failed: <span className="text-red-400 font-medium">{failedCount}</span>
        </span>
        {batchId && (
          <span className="text-[11px] font-mono text-gray-700 ml-auto">
            batch: {batchId}
          </span>
        )}
      </div>

      {/* Progress Bar */}
      {generating && stats.total > 0 && (
        <Card className="mb-4">
          <ProgressBar progress={((stats.done + stats.failed) / stats.total) * 100} />
          <p className="text-xs text-gray-500 mt-2 text-center">
            {stats.done + stats.failed} / {stats.total} completed
          </p>
        </Card>
      )}

      {/* Images Grid */}
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 animate-pulse">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="aspect-square bg-surface-card rounded-xl border border-border" />
          ))}
        </div>
      ) : images.length === 0 ? (
        <EmptyState
          icon={<ImageIcon />}
          title="No prompts to generate"
          description="Add image prompts in the Editor first"
        />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {images.map((img) => {
            const imgProgress = progress[img.fragment_id] ?? 0
            return (
              <Card key={img.fragment_id} className="p-0 overflow-hidden group animate-fade-in">
                {img.url && img.status === "done" ? (
                  <div className="aspect-square bg-surface-elevated overflow-hidden">
                    <img
                      src={img.url}
                      alt={`Scene ${img.fragment_id}`}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                  </div>
                ) : (
                  <div className="aspect-square bg-surface-elevated flex flex-col items-center justify-center gap-2">
                    {img.status === "generating" ? (
                      <>
                        <Loader2 className="w-6 h-6 text-accent animate-spin" />
                        <div className="w-3/4">
                          <ProgressBar progress={imgProgress} />
                        </div>
                        <span className="text-xs text-gray-500">{Math.round(imgProgress)}%</span>
                      </>
                    ) : img.status === "failed" ? (
                      <>
                        <XCircle className="w-8 h-8 text-red-500/40" />
                        <span className="text-[11px] text-red-500/60">Failed</span>
                      </>
                    ) : img.status === "done" ? (
                      <CheckCircle className="w-8 h-8 text-green-500/40" />
                    ) : (
                      <ImageIcon className="w-8 h-8 text-gray-700" />
                    )}
                  </div>
                )}
                <div className="p-2 flex items-center justify-between">
                  <span className="text-xs font-mono text-gray-600">
                    #{img.fragment_id}
                  </span>
                  <Badge
                    variant={
                      img.status === "done"
                        ? "success"
                        : img.status === "generating"
                          ? "info"
                          : img.status === "failed"
                            ? "error"
                            : "default"
                    }
                  >
                    {img.status}
                  </Badge>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
