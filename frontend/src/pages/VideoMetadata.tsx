import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import {
  Sparkles, Copy, Check, RefreshCw, FileText, Hash, Tag, Users,
  Target, PlaySquare, Image as ImageIcon, Lightbulb, ExternalLink,
  Edit3, Save,
} from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import EmptyState from "../components/EmptyState"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"

interface TitleVariant {
  variant: number
  title: string
  strategy: string
  target_keyword: string
}

interface Chapter {
  timestamp: string
  title: string
}

interface Description {
  primary: string
  body: string
  cta: string
  chapters: Chapter[]
  links_suggestion: string
}

interface ThumbnailOverlay {
  text: string
  style: string
}

interface SeoKeyword {
  keyword: string
  volume: string
  type: string
}

interface TargetAudience {
  age_range: string
  interests: string[]
  pain_points: string[]
  value_proposition: string
}

interface Metadata {
  generated_at?: string
  generated_from_length?: number
  title_variants?: TitleVariant[]
  description?: Description
  tags?: string[]
  hashtags?: string[]
  category?: string
  thumbnail_text_overlays?: ThumbnailOverlay[]
  seo_keywords?: SeoKeyword[]
  target_audience?: TargetAudience
  end_screen_suggestions?: string[]
  cards_suggestions?: string[]
}

function CopyBtn({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      toast(`${label} copied`, "success")
      setTimeout(() => setCopied(false), 2000)
    } catch { toast("Failed to copy", "error") }
  }
  return (
    <button onClick={handleCopy} className="text-xs text-gray-500 hover:text-accent transition-colors flex items-center gap-1 shrink-0">
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

function SectionHeader({ title, icon, children }: { title: string; icon: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3 pb-2 border-b border-border">
      <div className="flex items-center gap-2">
        <span className="text-accent">{icon}</span>
        <h3 className="text-sm font-semibold text-foreground dark:text-white font-sans">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function VariantCard({ variant, selected, onSelect }: { variant: TitleVariant; selected: boolean; onSelect: () => void }) {
  return (
    <div
      className={`p-3 rounded-lg border cursor-pointer transition-all ${
        selected ? "border-accent bg-accent/5 ring-1 ring-accent/30" : "border-border hover:border-accent/30"
      }`}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-mono text-gray-600 bg-surface-hover px-1.5 py-0.5 rounded">
              #{variant.variant}
            </span>
            <span className="text-[10px] font-mono text-accent">{variant.strategy}</span>
            <span className="text-[10px] font-mono text-gray-600">keyword: {variant.target_keyword}</span>
          </div>
          <p className="text-sm text-foreground dark:text-white font-body">{variant.title}</p>
          <p className="text-[11px] text-gray-600 mt-0.5 font-mono">{variant.title.length} chars</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <CopyBtn text={variant.title} label={`Title #${variant.variant}`} />
        </div>
      </div>
    </div>
  )
}

function TagCloud({ tags, icon }: { tags?: string[]; icon?: React.ReactNode }) {
  if (!tags || tags.length === 0) return <p className="text-xs text-gray-600 py-2">No tags generated</p>
  return (
    <div className="flex flex-wrap gap-1.5">
      {icon}
      {tags.map((t, i) => (
        <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-surface-hover text-gray-300 border border-border font-mono">
          {t.startsWith("#") ? t : `#${t}`}
        </span>
      ))}
    </div>
  )
}

export default function VideoMetadata() {
  const { projectId } = useParams<{ projectId: string }>()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [projectTitle, setProjectTitle] = useState("")
  const [text, setText] = useState("")
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [metadata, setMetadata] = useState<Metadata | null>(null)
  const [selectedTitle, setSelectedTitle] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [editData, setEditData] = useState<Metadata | null>(null)

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => setProjectTitle(p.title || p.name)).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    api.getScript(projectId).then((res) => {
      if (res.text) setText(res.text)
    }).catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    api.getVideoMetadata(projectId).then((res) => {
      if (res.metadata) {
        setMetadata(res.metadata as Metadata)
        setSelectedTitle(0)
      }
    }).catch(() => {})
  }, [projectId])

  const handleGenerate = async () => {
    if (!projectId || !text.trim()) return
    setLoading(true)
    try {
      const res = await api.generateVideoMetadata(projectId, { text: text.trim() })
      setMetadata(res as unknown as Metadata)
      setSelectedTitle(0)
      toast("Metadata generated successfully", "success")
    } catch (err: any) {
      toast(err?.message ?? "Failed to generate metadata", "error")
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!projectId || !editData) return
    setSaving(true)
    try {
      await api.updateVideoMetadata(projectId, editData as Record<string, any>)
      setMetadata(editData)
      setEditing(false)
      toast("Metadata saved", "success")
    } catch (err: any) {
      toast(err?.message ?? "Failed to save", "error")
    } finally {
      setSaving(false)
    }
  }

  const handleValidateChapters = async () => {
    if (!projectId) return
    setValidating(true)
    try {
      const res = await api.validateChapters(projectId)
      setMetadata(res as unknown as Metadata)
      toast("Timestamps validated against word timestamps", "success")
    } catch (err: any) {
      toast(err?.message ?? "Failed to validate", "error")
    } finally {
      setValidating(false)
    }
  }

  const copyAll = async () => {
    if (!metadata) return
    const parts: string[] = []
    if (metadata.title_variants?.length) {
      parts.push("=== TITLE VARIANTS ===")
      metadata.title_variants.forEach((v) => parts.push(`#${v.variant} (${v.strategy}): ${v.title}`))
      parts.push("")
    }
    if (metadata.description) {
      parts.push("=== DESCRIPTION ===")
      parts.push(metadata.description.primary)
      parts.push("")
      parts.push(metadata.description.body)
      parts.push("")
      parts.push(metadata.description.cta)
      if (metadata.description.chapters?.length) {
        parts.push("")
        parts.push("CHAPTERS:")
        metadata.description.chapters.forEach((c) => parts.push(`${c.timestamp} - ${c.title}`))
      }
      parts.push("")
    }
    if (metadata.tags?.length) parts.push("TAGS: " + metadata.tags.join(", "))
    if (metadata.hashtags?.length) parts.push("HASHTAGS: " + metadata.hashtags.map((h) => h.startsWith("#") ? h : `#${h}`).join(" "))
    if (metadata.category) parts.push("CATEGORY: " + metadata.category)
    try {
      await navigator.clipboard.writeText(parts.join("\n"))
      toast("All metadata copied", "success")
    } catch { toast("Failed to copy", "error") }
  }

  if (!projectId) {
    return (
      <EmptyState icon={<Sparkles />} title="No project selected"
        description="Select a project from the Dashboard to generate video metadata" />
    )
  }

  return (
    <div>
      <PageHeader title={projectTitle || "Video Metadata"} description="SEO metadata for YouTube: titles, description, tags, chapters, and more"
        backTo={`/workflow/${projectId}`}
        actions={
          <div className="flex items-center gap-2">
            {metadata && !editing && (
              <button onClick={() => { setEditData(JSON.parse(JSON.stringify(metadata))); setEditing(true) }}
                className="btn-secondary"><Edit3 className="w-4 h-4" /> Edit</button>
            )}
            {editing && (
              <button onClick={handleSave} disabled={saving}
                className="btn-primary"><Save className="w-4 h-4" /> {saving ? "Saving..." : "Save"}</button>
            )}
            <button onClick={handleGenerate} disabled={loading || !text.trim()}
              className="btn-primary">
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {loading ? "Generating..." : "Generate"}
            </button>
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left sidebar — input + status */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <SectionHeader title="Script" icon={<FileText />} />
            <textarea className="w-full h-48 bg-surface-hover border border-border rounded-lg px-3 py-2 text-sm text-gray-300 font-body placeholder:text-gray-700 focus:outline-none focus:border-accent resize-y"
              value={text} onChange={(e) => setText(e.target.value)}
              placeholder="Script text loaded automatically. Edit if needed..." />
          </Card>

          {metadata && (
            <Card>
              <SectionHeader title="SEO Summary" icon={<Target />} />
              <div className="space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-gray-500">Title variants</span><span className="text-foreground dark:text-white font-mono">{metadata.title_variants?.length ?? 0}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Chapters</span><span className="text-foreground dark:text-white font-mono">{metadata.description?.chapters?.length ?? 0}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Tags</span><span className="text-foreground dark:text-white font-mono">{metadata.tags?.length ?? 0}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Hashtags</span><span className="text-foreground dark:text-white font-mono">{metadata.hashtags?.length ?? 0}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Category</span><span className="text-foreground dark:text-white font-mono truncate max-w-[140px]">{metadata.category ?? "—"}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Text length</span><span className="text-foreground dark:text-white font-mono">{metadata.generated_from_length ?? 0} chars</span></div>
                {metadata.generated_at && (
                  <div className="flex justify-between"><span className="text-gray-500">Generated</span><span className="text-foreground dark:text-white font-mono text-[10px]">{new Date(metadata.generated_at).toLocaleString()}</span></div>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* Main content */}
        <div className="lg:col-span-3 space-y-4">
          {!metadata && !loading && (
            <Card>
              <div className="text-center py-12">
                <Sparkles className="w-14 h-14 text-gray-800 mx-auto mb-3" />
                <p className="text-sm text-gray-500 font-body mb-2">No metadata generated yet</p>
                <p className="text-xs text-gray-700 font-body">Click "Generate" to create SEO-optimized metadata for your video using Gemini Web</p>
              </div>
            </Card>
          )}

          {loading && (
            <Card>
              <div className="text-center py-12">
                <RefreshCw className="w-10 h-10 text-accent animate-spin mx-auto mb-3" />
                <p className="text-sm text-gray-400 font-body">Generating metadata with Gemini Web...</p>
                <p className="text-xs text-gray-700 mt-2">This may take 20-30 seconds</p>
              </div>
            </Card>
          )}

          {metadata && !editing && (
            <>
              <div className="flex items-center justify-end gap-2">
                <button onClick={copyAll} className="text-xs text-accent hover:text-accent-light transition-colors flex items-center gap-1">
                  <Copy className="w-3.5 h-3.5" /> Copy All
                </button>
              </div>

              {/* Title Variants */}
              <Card>
                <SectionHeader title="Title Variants" icon={<PlaySquare />}>
                  <div className="flex items-center gap-2">
                    {selectedTitle !== null && metadata.title_variants?.[selectedTitle] && (
                      <CopyBtn text={metadata.title_variants[selectedTitle].title} label="Selected title" />
                    )}
                  </div>
                </SectionHeader>
                <div className="space-y-2">
                  {metadata.title_variants?.map((v) => (
                    <VariantCard
                      key={v.variant}
                      variant={v}
                      selected={selectedTitle === v.variant - 1}
                      onSelect={() => setSelectedTitle(v.variant - 1)}
                    />
                  ))}
                </div>
              </Card>

              {/* Description + Chapters */}
              <Card>
                <SectionHeader title="Description" icon={<FileText />}>
                  <CopyBtn text={`${metadata.description?.primary}\n\n${metadata.description?.body}\n\n${metadata.description?.cta}`} label="Description" />
                </SectionHeader>
                {metadata.description && (
                  <div className="space-y-3">
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-xs text-gray-500 mb-1 font-semibold">Primary Hook</p>
                      <p className="text-sm text-foreground dark:text-white font-body">{metadata.description.primary}</p>
                    </div>
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-xs text-gray-500 mb-1 font-semibold">Body</p>
                      <p className="text-sm text-gray-300 font-body whitespace-pre-wrap">{metadata.description.body}</p>
                    </div>
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-xs text-gray-500 mb-1 font-semibold">Call to Action</p>
                      <p className="text-sm text-accent font-body">{metadata.description.cta}</p>
                    </div>
                    {metadata.description.links_suggestion && (
                      <div className="bg-surface-hover rounded-lg p-3 border border-border">
                        <p className="text-xs text-gray-500 mb-1 font-semibold">Links Suggestion</p>
                        <p className="text-sm text-gray-300 font-body">{metadata.description.links_suggestion}</p>
                      </div>
                    )}
                    {metadata.description.chapters && metadata.description.chapters.length > 0 && (
                      <div className="bg-surface-hover rounded-lg p-3 border border-border">
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-xs text-gray-500 font-semibold">Chapters ({metadata.description.chapters.length})</p>
                          <div className="flex items-center gap-2">
                            <button onClick={handleValidateChapters} disabled={validating}
                              className="text-xs text-gray-500 hover:text-accent transition-colors flex items-center gap-1">
                              <RefreshCw className={`w-3 h-3 ${validating ? "animate-spin" : ""}`} />
                              {validating ? "Validating..." : "Validate timestamps"}
                            </button>
                            <CopyBtn text={metadata.description.chapters.map((c) => `${c.timestamp} - ${c.title}`).join("\n")} label="Chapters" />
                          </div>
                        </div>
                        <div className="space-y-1">
                          {metadata.description.chapters.map((c, i) => (
                            <div key={i} className="flex items-center gap-3 text-sm">
                              <span className="font-mono text-accent text-xs shrink-0 w-12">{c.timestamp}</span>
                              <span className="text-gray-300">{c.title}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </Card>

              {/* Tags & Hashtags */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card>
                  <SectionHeader title="Tags" icon={<Tag />}>
                    <CopyBtn text={metadata.tags?.join(", ") ?? ""} label="Tags" />
                  </SectionHeader>
                  <TagCloud tags={metadata.tags} />
                </Card>
                <Card>
                  <SectionHeader title="Hashtags" icon={<Hash />}>
                    <CopyBtn text={(metadata.hashtags ?? []).map((h) => h.startsWith("#") ? h : `#${h}`).join(" ")} label="Hashtags" />
                  </SectionHeader>
                  <TagCloud tags={metadata.hashtags} icon={<Hash className="w-3.5 h-3.5 text-accent" />} />
                </Card>
              </div>

              {/* Category + Thumbnail + SEO */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                  <SectionHeader title="Category" icon={<PlaySquare />} />
                  <p className="text-sm text-foreground dark:text-white font-body bg-surface-hover rounded-lg px-3 py-2 border border-border">{metadata.category ?? "—"}</p>
                </Card>
                <Card>
                  <SectionHeader title="Thumbnail Text" icon={<ImageIcon />}>
                    <CopyBtn text={(metadata.thumbnail_text_overlays ?? []).map((o) => o.text).join(" | ")} label="Thumbnail" />
                  </SectionHeader>
                  <div className="space-y-2">
                    {(metadata.thumbnail_text_overlays ?? []).map((o, i) => (
                      <div key={i} className="bg-surface-hover rounded-lg px-3 py-2 border border-border">
                        <p className="text-sm text-foreground dark:text-white font-body">{o.text}</p>
                        <p className="text-[10px] text-gray-600 mt-0.5 font-mono">{o.style}</p>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card>
                  <SectionHeader title="SEO Keywords" icon={<Target />} />
                  <div className="space-y-1.5">
                    {(metadata.seo_keywords ?? []).map((k, i) => (
                      <div key={i} className="flex items-center justify-between bg-surface-hover rounded px-2 py-1.5 border border-border">
                        <div className="min-w-0">
                          <p className="text-xs text-foreground dark:text-white font-mono truncate">{k.keyword}</p>
                          <p className="text-[10px] text-gray-600">{k.type}</p>
                        </div>
                        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                          k.volume === "alto" ? "bg-green-500/10 text-green-400" :
                          k.volume === "medio" ? "bg-amber-500/10 text-amber-400" :
                          "bg-gray-500/10 text-gray-400"
                        }`}>{k.volume}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>

              {/* Target Audience */}
              {metadata.target_audience && (
                <Card>
                  <SectionHeader title="Target Audience" icon={<Users />} />
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Age Range</p>
                      <p className="text-sm text-foreground dark:text-white font-mono">{metadata.target_audience.age_range}</p>
                    </div>
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Interests</p>
                      <div className="flex flex-wrap gap-1">{metadata.target_audience.interests.map((i, j) => (
                        <span key={j} className="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">{i}</span>
                      ))}</div>
                    </div>
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Pain Points</p>
                      <div className="flex flex-wrap gap-1">{metadata.target_audience.pain_points.map((p, j) => (
                        <span key={j} className="text-xs px-1.5 py-0.5 rounded bg-red-500/10 text-red-400">{p}</span>
                      ))}</div>
                    </div>
                    <div className="bg-surface-hover rounded-lg p-3 border border-border">
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">Value Prop</p>
                      <p className="text-xs text-gray-300">{metadata.target_audience.value_proposition}</p>
                    </div>
                  </div>
                </Card>
              )}

              {/* End Screen & Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card>
                  <SectionHeader title="End Screen" icon={<ExternalLink />}>
                    <CopyBtn text={(metadata.end_screen_suggestions ?? []).join(", ")} label="End screen" />
                  </SectionHeader>
                  <ul className="space-y-1">
                    {(metadata.end_screen_suggestions ?? []).map((s, i) => (
                      <li key={i} className="text-sm text-gray-300 font-body flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-accent/50 shrink-0" />
                        {s}
                      </li>
                    ))}
                  </ul>
                </Card>
                <Card>
                  <SectionHeader title="Cards" icon={<Lightbulb />}>
                    <CopyBtn text={(metadata.cards_suggestions ?? []).join(", ")} label="Cards" />
                  </SectionHeader>
                  <ul className="space-y-1">
                    {(metadata.cards_suggestions ?? []).map((s, i) => (
                      <li key={i} className="text-sm text-gray-300 font-body flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-accent/50 shrink-0" />
                        {s}
                      </li>
                    ))}
                  </ul>
                </Card>
              </div>
            </>
          )}

          {/* Edit mode */}
          {metadata && editing && editData && (
            <Card>
              <SectionHeader title="Editing" icon={<Edit3 />} />
              <p className="text-xs text-gray-500 mb-4">Edit the JSON directly. Be careful with the structure.</p>
              <textarea
                className="w-full h-96 bg-surface-hover border border-border rounded-lg px-3 py-2 text-xs text-gray-300 font-mono focus:outline-none focus:border-accent resize-y"
                value={JSON.stringify(editData, null, 2)}
                onChange={(e) => {
                  try { setEditData(JSON.parse(e.target.value)) } catch {}
                }}
              />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
