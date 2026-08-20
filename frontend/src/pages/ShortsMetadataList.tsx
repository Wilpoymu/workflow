import { useEffect, useMemo, useState } from "react"
import { useParams, Link } from "react-router-dom"
import {
  Sparkles, Copy, Check, RefreshCw, Smartphone, PlaySquare,
  ExternalLink, FileText, Music,
} from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import EmptyState from "../components/EmptyState"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"

interface ShortMetadataEntry {
  index: string
  generated_from: string
  generated_at: string
  tiktok?: {
    title: string
    description: string
    hashtags: string[]
    tags: string[]
    audio_suggestion: string | null
  }
  youtube?: {
    title: string
    description: string
    tags: string[]
    hashtags: string[]
    category: string
  }
}

function CopyBtn({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      toast(`${label} copied`, "success")
      setTimeout(() => setCopied(false), 2000)
    } catch { toast("Failed to copy", "error") }
  }
  return (
    <button onClick={copy} className="text-xs text-gray-500 hover:text-accent transition-colors flex items-center gap-1 shrink-0">
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

function TagCloud({ tags, color }: { tags: string[]; color?: string }) {
  if (!tags?.length) return <p className="text-xs text-gray-700 py-1">None</p>
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t, i) => (
        <span key={i} className={`text-xs px-2 py-0.5 rounded-full border font-mono ${
          color || "bg-surface-hover text-gray-300 border-border"
        }`}>
          {t.startsWith("#") ? t : `#${t}`}
        </span>
      ))}
    </div>
  )
}

function PlatformSection({ data, platform }: { data: ShortMetadataEntry["tiktok"] | ShortMetadataEntry["youtube"]; platform: "tiktok" | "youtube" }) {
  const [showAll, setShowAll] = useState(false)
  if (!data) return null

  const isLong = data.description.length > 200
  const icon = platform === "tiktok" ? <Smartphone className="w-4 h-4 text-pink-400" /> : <PlaySquare className="w-4 h-4 text-red-400" />

  return (
    <div className={`rounded-lg border p-4 ${platform === "tiktok" ? "border-pink-500/10 bg-pink-500/[0.02]" : "border-red-500/10 bg-red-500/[0.02]"}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {icon}
          <h4 className="text-xs font-semibold text-foreground dark:text-white uppercase tracking-wider">{platform === "tiktok" ? "TikTok" : "YouTube Shorts"}</h4>
        </div>
        <CopyBtn text={`${data.title}\n\n${data.description}`} label={`${platform} metadata`} />
      </div>

      {/* Title */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-gray-600 font-semibold uppercase">Title</span>
          <CopyBtn text={data.title} label="Title" />
        </div>
        <p className="text-sm text-foreground dark:text-white font-body bg-surface-hover rounded-lg px-3 py-2 border border-border">{data.title}</p>
        <p className="text-[11px] text-gray-600 mt-0.5 font-mono">{data.title.length} chars</p>
      </div>

      {/* Description */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-gray-600 font-semibold uppercase">Description</span>
          <CopyBtn text={data.description} label="Description" />
        </div>
        <p className={`text-sm text-gray-300 font-body bg-surface-hover rounded-lg px-3 py-2 border border-border ${showAll || !isLong ? "" : "line-clamp-2"}`}>
          {data.description}
        </p>
        {isLong && (
          <button onClick={() => setShowAll(!showAll)} className="text-xs text-accent hover:text-accent-light mt-1">
            {showAll ? "Show less" : "Show more"}
          </button>
        )}
      </div>

      {/* Tags */}
      {"tags" in data && data.tags?.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-gray-600 font-semibold uppercase">Tags</span>
            <CopyBtn text={data.tags.join(", ")} label="Tags" />
          </div>
          <TagCloud tags={data.tags} />
        </div>
      )}

      {/* Hashtags */}
      {"hashtags" in data && data.hashtags?.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-gray-600 font-semibold uppercase">Hashtags</span>
            <CopyBtn text={data.hashtags.map(h => h.startsWith("#") ? h : `#${h}`).join(" ")} label="Hashtags" />
          </div>
          <TagCloud tags={data.hashtags} color="bg-accent/10 text-accent border-accent/20" />
        </div>
      )}

      {/* TikTok Audio */}
      {platform === "tiktok" && (data as any).audio_suggestion && (
        <div className="flex items-center gap-2 text-xs text-gray-400 bg-surface-hover rounded-lg px-3 py-2 border border-border">
          <Music className="w-3.5 h-3.5 text-pink-400" />
          <span><span className="text-gray-600">Audio:</span> {(data as any).audio_suggestion}</span>
        </div>
      )}

      {/* YouTube Category */}
      {platform === "youtube" && (data as any).category && (
        <div className="flex items-center gap-2 text-xs text-gray-400 bg-surface-hover rounded-lg px-3 py-2 border border-border">
          <PlaySquare className="w-3.5 h-3.5 text-red-400" />
          <span><span className="text-gray-600">Category:</span> {(data as any).category}</span>
        </div>
      )}
    </div>
  )
}

export default function ShortsMetadataList() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [projectTitle, setProjectTitle] = useState("")
  const [metadataMap, setMetadataMap] = useState<Record<string, ShortMetadataEntry>>({})
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState<string | null>(null)
  const [newIndex, setNewIndex] = useState("")
  const [newText, setNewText] = useState("")

  useEffect(() => { if (projectId) setActiveProject(projectId) }, [projectId, setActiveProject])
  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => setProjectTitle(p.title || p.name)).catch(() => {})
  }, [projectId])
  useEffect(() => { if (!projectId) return; loadMetadata() }, [projectId])

  const loadMetadata = async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const res = await api.getShortsMetadata(projectId)
      if (res.metadata && typeof res.metadata === "object" && !Array.isArray(res.metadata)) {
        setMetadataMap(res.metadata as Record<string, ShortMetadataEntry>)
      }
    } catch {}
    setLoading(false)
  }

  const handleGenerate = async (index: string, text: string) => {
    if (!projectId) return
    setGenerating(index)
    try {
      await api.generateShortsMetadata(projectId, { index, text: text.trim(), platform: "both" })
      toast("Metadata generated", "success")
      await loadMetadata()
    } catch (err: any) {
      toast(err?.message ?? "Failed to generate metadata", "error")
    } finally {
      setGenerating(null)
    }
  }

  const handleCopyEntry = (entry: ShortMetadataEntry) => {
    const parts: string[] = []
    for (const p of ["tiktok", "youtube"] as const) {
      const pd = entry[p]
      if (!pd) continue
      parts.push(`=== ${p === "tiktok" ? "TIKTOK" : "YOUTUBE SHORTS"} ===`)
      parts.push(pd.title)
      parts.push("")
      parts.push(pd.description)
      if (pd.tags?.length) parts.push("Tags: " + pd.tags.join(", "))
      if (pd.hashtags?.length) parts.push("Hashtags: " + pd.hashtags.map(h => h.startsWith("#") ? h : `#${h}`).join(" "))
      parts.push("")
    }
    navigator.clipboard.writeText(parts.join("\n")).then(() => toast("Entry copied", "success")).catch(() => {})
  }

  const sorted = useMemo(() =>
    Object.entries(metadataMap).sort(([a], [b]) => {
      const na = parseInt(a), nb = parseInt(b)
      if (!isNaN(na) && !isNaN(nb)) return na - nb
      return a.localeCompare(b)
    }), [metadataMap])

  const stats = useMemo(() => ({
    total: sorted.length,
    withTikTok: sorted.filter(([, e]) => !!e.tiktok).length,
    withYouTube: sorted.filter(([, e]) => !!e.youtube).length,
  }), [sorted])

  if (!projectId) {
    return <EmptyState icon={<Sparkles />} title="No project selected" description="Select a project from the Dashboard" />
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || "Shorts Metadata"}
        description="SEO metadata for each short: titles, hashtags, and descriptions optimized for TikTok and YouTube Shorts"
        backTo={`/shorts/${projectId}`}
      />

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">Summary</h3>
            {loading ? (
              <div className="animate-pulse space-y-2">
                {[1,2,3].map(i => <div key={i} className="h-4 bg-surface-hover rounded" />)}
              </div>
            ) : (
              <div className="space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-gray-500">Total shorts</span><span className="text-foreground dark:text-white font-mono">{stats.total}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">With TikTok</span><span className="text-pink-400 font-mono">{stats.withTikTok}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">With YouTube</span><span className="text-red-400 font-mono">{stats.withYouTube}</span></div>
              </div>
            )}
          </Card>

          {/* Generate new */}
          <Card>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Generate New</h3>
            <div className="space-y-2">
              <input
                type="text"
                placeholder="Index (e.g. 0, manual_2)"
                className="w-full bg-surface-hover border border-border rounded-lg px-3 py-2 text-xs text-gray-300 font-mono focus:outline-none focus:border-accent"
                value={newIndex}
                onChange={(e) => setNewIndex(e.target.value)}
              />
              <textarea
                placeholder="Paste the short text..."
                className="w-full bg-surface-hover border border-border rounded-lg px-3 py-2 text-xs text-gray-300 font-body focus:outline-none focus:border-accent resize-y h-20"
                value={newText}
                onChange={(e) => setNewText(e.target.value)}
              />
              <button
                onClick={() => handleGenerate(newIndex || `manual_${Date.now()}`, newText)}
                disabled={generating !== null || !newIndex || !newText.trim()}
                className="btn-primary w-full text-xs"
              >
                {generating === (newIndex || "pending") ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : <Sparkles className="w-3 h-3" />}
                {generating ? "Generating..." : "Generate"}
              </button>
            </div>
          </Card>

          {projectId && (
            <Link to={`/shorts/${projectId}`}
              className="flex items-center gap-2 text-xs text-gray-500 hover:text-accent transition-colors px-3 py-2 rounded-lg bg-surface-hover border border-border">
              <ExternalLink className="w-3.5 h-3.5" />
              Go to Shorts page
            </Link>
          )}
        </div>

        {/* Main */}
        <div className="lg:col-span-3 space-y-4">
          {loading && (
            <Card>
              <div className="text-center py-10">
                <RefreshCw className="w-8 h-8 text-accent animate-spin mx-auto mb-2" />
                <p className="text-sm text-gray-400">Loading metadata...</p>
              </div>
            </Card>
          )}

          {!loading && sorted.length === 0 && (
            <Card>
              <div className="text-center py-14">
                <div className="w-14 h-14 rounded-xl bg-surface-hover flex items-center justify-center mx-auto mb-4">
                  <Sparkles className="w-7 h-7 text-gray-700" />
                </div>
                <p className="text-sm text-gray-400 font-body mb-1">No shorts metadata yet</p>
                <p className="text-xs text-gray-600 font-body mb-5">Generate metadata from the Shorts page or use the form on the left</p>
                <Link to={`/shorts/${projectId}`} className="btn-primary inline-flex items-center gap-2">
                  <ExternalLink className="w-4 h-4" /> Go to Shorts
                </Link>
              </div>
            </Card>
          )}

          {sorted.map(([index, entry]) => (
            <Card key={index} className="hover:border-accent/20 transition-colors">
              {/* Header */}
              <div className="flex items-start justify-between gap-3 mb-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-accent bg-accent/10 px-2 py-0.5 rounded font-semibold">#{index}</span>
                  <span className="text-xs text-gray-600 font-mono">
                    {entry.generated_at ? new Date(entry.generated_at).toLocaleString() : ""}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleGenerate(index, entry.generated_from)}
                    disabled={generating === index}
                    className="text-xs text-gray-500 hover:text-accent transition-colors flex items-center gap-1"
                  >
                    <RefreshCw className={`w-3 h-3 ${generating === index ? "animate-spin" : ""}`} />
                    Regenerate
                  </button>
                  <button onClick={() => handleCopyEntry(entry)}
                    className="text-xs text-accent hover:text-accent-light transition-colors flex items-center gap-1">
                    <Copy className="w-3.5 h-3.5" /> Copy all
                  </button>
                </div>
              </div>

              {/* Text preview */}
              <div className="mb-4 bg-surface-hover rounded-lg px-3 py-2 border border-border">
                <div className="flex items-center gap-1.5 mb-1">
                  <FileText className="w-3 h-3 text-gray-600" />
                  <span className="text-[10px] text-gray-600 font-semibold uppercase">Script preview</span>
                </div>
                <p className="text-xs text-gray-400 font-body line-clamp-2">{entry.generated_from || "—"}</p>
              </div>

              {/* Platform sections */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <PlatformSection data={entry.tiktok} platform="tiktok" />
                <PlatformSection data={entry.youtube} platform="youtube" />
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}
