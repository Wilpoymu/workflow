import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { Hash, Copy, Check, RefreshCw, FileText, Smartphone, PlaySquare, Sparkles } from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import EmptyState from "../components/EmptyState"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"

interface TikTokMetadata {
  title: string
  description: string
  hashtags: string[]
  tags: string[]
  audio_suggestion: string | null
}

interface YouTubeMetadata {
  title: string
  description: string
  tags: string[]
  hashtags: string[]
  category: string
}

interface MetadataResult {
  tiktok?: TikTokMetadata
  youtube?: YouTubeMetadata
  generated_from?: string
}

type Platform = "both" | "tiktok" | "youtube"

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      toast(`${label} copied`, "success")
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast("Failed to copy", "error")
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="text-xs text-gray-500 hover:text-accent transition-colors flex items-center gap-1"
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

function TagList({ tags, icon }: { tags: string[]; icon?: React.ReactNode }) {
  if (!tags || tags.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {icon}
      {tags.map((tag, i) => (
        <span
          key={i}
          className="text-xs px-2 py-0.5 rounded-full bg-surface-hover text-gray-300 border border-border font-mono"
        >
          {tag.startsWith("#") ? tag : `#${tag}`}
        </span>
      ))}
    </div>
  )
}

function PlatformCard({
  platform,
  data,
  label,
  icon,
}: {
  platform: "tiktok" | "youtube"
  data: TikTokMetadata | YouTubeMetadata | undefined
  label: string
  icon: React.ReactNode
}) {
  if (!data) return null

  const allTags = "hashtags" in data ? (data as any).hashtags?.join(" ") || "" : ""
  const fullDescription = `${data.title}\n\n${data.description}\n\n${(data as any).tags?.join(", ") || ""}\n${allTags}`

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-sm font-semibold text-foreground dark:text-white font-sans">{label}</h3>
        </div>
        <CopyButton text={fullDescription} label={`${label} metadata`} />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Title</label>
          <CopyButton text={data.title} label="Title" />
        </div>
        <p className="text-sm text-foreground dark:text-white font-body bg-surface-hover rounded-lg px-3 py-2 border border-border">
          {data.title}
        </p>
        <p className="text-[11px] text-gray-600 mt-1 font-mono">{data.title.length} chars</p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Description</label>
          <CopyButton text={data.description} label="Description" />
        </div>
        <p className="text-sm text-gray-300 font-body bg-surface-hover rounded-lg px-3 py-2 border border-border whitespace-pre-wrap">
          {data.description}
        </p>
        <p className="text-[11px] text-gray-600 mt-1 font-mono">{data.description.length} chars</p>
      </div>

      {"tags" in data && data.tags && data.tags.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Tags</label>
            <CopyButton text={data.tags.join(", ")} label="Tags" />
          </div>
          <TagList tags={data.tags} />
        </div>
      )}

      {"hashtags" in data && (data as any).hashtags && (data as any).hashtags.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Hashtags</label>
            <CopyButton text={(data as any).hashtags.map((h: string) => h.startsWith("#") ? h : `#${h}`).join(" ")} label="Hashtags" />
          </div>
          <TagList tags={(data as any).hashtags} icon={<Hash className="w-3.5 h-3.5 text-accent" />} />
        </div>
      )}

      {platform === "tiktok" && (data as TikTokMetadata).audio_suggestion && (
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1 block">
            Audio Suggestion
          </label>
          <p className="text-sm text-gray-300 font-body">
            {(data as TikTokMetadata).audio_suggestion}
          </p>
        </div>
      )}

      {platform === "youtube" && (data as YouTubeMetadata).category && (
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1 block">
            Category
          </label>
          <p className="text-sm text-gray-300 font-body">
            {(data as YouTubeMetadata).category}
          </p>
        </div>
      )}
    </Card>
  )
}

export default function ShortsMetadata() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()
  const [projectTitle, setProjectTitle] = useState("")
  const [text, setText] = useState("")
  const [platform, setPlatform] = useState<Platform>("both")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<MetadataResult | null>(null)

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
    api.getScript(projectId).then((res) => {
      if (res.text) setText(res.text)
    }).catch(() => {})
  }, [projectId])

  const handleGenerate = async () => {
    if (!projectId || !text.trim()) return
    setLoading(true)
    setResult(null)
    try {
      const res = await api.generateShortsMetadataLegacy(projectId, { text: text.trim(), platform })
      setResult(res)
      const count = [res.tiktok, res.youtube].filter(Boolean).length
      toast(`Metadata generated for ${count} platform${count > 1 ? "s" : ""}`, "success")
    } catch (err: any) {
      toast(err?.message ?? "Failed to generate metadata", "error")
    } finally {
      setLoading(false)
    }
  }

  const handleCopyAll = async () => {
    if (!result) return
    const parts: string[] = []
    if (result.tiktok) {
      parts.push("=== TIKTOK ===")
      parts.push(result.tiktok.title)
      parts.push("")
      parts.push(result.tiktok.description)
      parts.push("")
      parts.push("Tags: " + result.tiktok.tags.join(", "))
      parts.push("Hashtags: " + result.tiktok.hashtags.map(h => h.startsWith("#") ? h : `#${h}`).join(" "))
      parts.push("")
    }
    if (result.youtube) {
      parts.push("=== YOUTUBE SHORTS ===")
      parts.push(result.youtube.title)
      parts.push("")
      parts.push(result.youtube.description)
      parts.push("")
      parts.push("Tags: " + result.youtube.tags.join(", "))
      parts.push("Hashtags: " + result.youtube.hashtags.map(h => h.startsWith("#") ? h : `#${h}`).join(" "))
      if (result.youtube.category) parts.push("Category: " + result.youtube.category)
    }
    try {
      await navigator.clipboard.writeText(parts.join("\n"))
      toast("All metadata copied to clipboard", "success")
    } catch {
      toast("Failed to copy", "error")
    }
  }

  if (!projectId) {
    return (
      <EmptyState
        icon={<Hash />}
        title="No project selected"
        description="Select a project from the Dashboard to generate Shorts metadata"
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Shorts Metadata"}
        description="Generate optimized titles, descriptions, and tags for TikTok and YouTube Shorts"
        backTo={`/workflow/${projectId}`}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left — Input */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <h3 className="text-sm font-semibold text-foreground dark:text-white mb-4 font-sans">Content</h3>

            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1.5 block">
                  Script Text
                </label>
                <textarea
                  className="w-full h-48 bg-surface-hover border border-border rounded-lg px-3 py-2 text-sm text-gray-300 font-body placeholder:text-gray-700 focus:outline-none focus:border-accent resize-y"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Paste or type the short's script text..."
                />
              </div>

              <div>
                <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1.5 block">
                  Platform
                </label>
                <div className="flex gap-2">
                  {(["both", "tiktok", "youtube"] as const).map((p) => (
                    <button
                      key={p}
                      onClick={() => setPlatform(p)}
                      className={`flex-1 text-xs py-2 rounded-lg border transition-all flex items-center justify-center gap-1.5 ${
                        platform === p
                          ? "border-accent bg-accent/10 text-accent"
                          : "border-border text-gray-500 hover:border-accent/30"
                      }`}
                    >
                      {p === "tiktok" && <Smartphone className="w-3.5 h-3.5" />}
                      {p === "youtube" && <PlaySquare className="w-3.5 h-3.5" />}
                      {p === "both" && <Sparkles className="w-3.5 h-3.5" />}
                      {p === "both" ? "Both" : p === "tiktok" ? "TikTok" : "YouTube"}
                    </button>
                  ))}
                </div>
              </div>

              <button
                className="btn-primary w-full"
                onClick={handleGenerate}
                disabled={loading || !text.trim()}
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Generate Metadata
                  </>
                )}
              </button>
            </div>
          </Card>
        </div>

        {/* Right — Results */}
        <div className="lg:col-span-2 space-y-4">
          {!result && !loading && (
            <Card>
              <div className="text-center py-10">
                <FileText className="w-12 h-12 text-gray-800 mx-auto mb-3" />
                <p className="text-sm text-gray-500 font-body mb-1">
                  Enter your short's script and generate metadata
                </p>
                <p className="text-xs text-gray-700 font-body">
                  Get optimized titles, descriptions, tags, and hashtags for each platform
                </p>
              </div>
            </Card>
          )}

          {loading && (
            <Card>
              <div className="text-center py-10">
                <RefreshCw className="w-10 h-10 text-accent animate-spin mx-auto mb-3" />
                <p className="text-sm text-gray-400 font-body">Generating metadata with AI...</p>
              </div>
            </Card>
          )}

          {result && (
            <>
              <div className="flex items-center justify-end">
                <button
                  onClick={handleCopyAll}
                  className="text-xs text-accent hover:text-accent-light transition-colors flex items-center gap-1"
                >
                  <Copy className="w-3.5 h-3.5" />
                  Copy All
                </button>
              </div>

              <PlatformCard
                platform="tiktok"
                data={result.tiktok}
                label="TikTok"
                icon={<Smartphone className="w-4 h-4 text-pink-400" />}
              />
              <PlatformCard
                platform="youtube"
                data={result.youtube}
                label="YouTube Shorts"
                icon={<PlaySquare className="w-4 h-4 text-red-400" />}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
