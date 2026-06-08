import { useEffect, useState, useCallback, useRef } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Image as ImageIcon, FileText, Save, ChevronDown, ChevronRight, Loader2, Hash, AlignLeft, TextQuote, Layers, MessageSquareText, Clock, Scissors, Sparkles } from "lucide-react"
import PageHeader from "../components/PageHeader"
import FragmentList from "../components/FragmentList"
import Card from "../components/Card"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type { Fragment as FragmentType } from "../types"

const statIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  Words: Hash,
  Chars: AlignLeft,
  Lines: TextQuote,
  Paragraphs: Layers,
  Sentences: MessageSquareText,
  "Speaking time": Clock,
}

const IMAGE_STYLES = [
  "Fotorrealista",
  "Animacion 3D",
  "Anime/Manga",
  "Arte Conceptual",
  "Cinematico",
  "Comic",
  "Acuarela",
] as const

function ScriptStat({ label, value }: { label: string; value: string | number }) {
  const Icon = statIcons[label]
  return (
    <span className="inline-flex items-center gap-1 bg-surface-hover px-2 py-1 rounded-md" title={label}>
      {Icon && <Icon className="w-3 h-3 text-gray-600" />}
      <span className="text-gray-400">{label}:</span>
      <span className="text-gray-300 font-semibold">{value}</span>
    </span>
  )
}

export default function Editor() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()
  const [fragments, setFragments] = useState<FragmentType[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [projectTitle, setProjectTitle] = useState("")

  // Full script state
  const [scriptText, setScriptText] = useState("")
  const [scriptLoaded, setScriptLoaded] = useState(false)
  const [scriptLoading, setScriptLoading] = useState(false)
  const [scriptSaving, setScriptSaving] = useState(false)
  const [scriptDirty, setScriptDirty] = useState(false)
  const [scriptOpen, setScriptOpen] = useState(true)
  const [fragmenting, setFragmenting] = useState(false)
  const [generatingPrompts, setGeneratingPrompts] = useState(false)
  const [generatingElapsed, setGeneratingElapsed] = useState(0)
  const [generatingTotal, setGeneratingTotal] = useState(0)
  const [currentBatch, setCurrentBatch] = useState(0)
  const [totalBatches, setTotalBatches] = useState(0)
  const promptEsRef = useRef<EventSource | null>(null)
  const [imageStyle, setImageStyle] = useState<string>("Cinematico")
  const [customStyle, setCustomStyle] = useState(false)

  // Auto-save style when it changes (debounced)
  useEffect(() => {
    if (!projectId || !imageStyle.trim()) return
    const timer = setTimeout(() => {
      api.setPromptStyle(projectId, imageStyle).catch(() => {})
    }, 500)
    return () => clearTimeout(timer)
  }, [projectId, imageStyle])

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => {
      setProjectTitle(p.title || p.name)
      // Load saved prompt style
      const savedStyle = p.prompt_style
      if (savedStyle && savedStyle !== "Cinematico") {
        setImageStyle(savedStyle)
        if (!(IMAGE_STYLES as readonly string[]).includes(savedStyle as any)) {
          setCustomStyle(true)
        }
      }
    }).catch(() => {})
  }, [projectId])

  // Load full script text
  useEffect(() => {
    if (!projectId || scriptLoaded) return
    setScriptLoading(true)
    api.getScript(projectId)
      .then((res) => {
        setScriptText(res.text)
        setScriptLoaded(true)
      })
      .catch(() => {
        // 404 means no script yet — that's fine
        setScriptLoaded(true)
      })
      .finally(() => setScriptLoading(false))
  }, [projectId, scriptLoaded])

  const load = useCallback(async () => {
    if (!projectId) return
    try {
      const res = await api.listFragments(projectId)
      setFragments(res.fragments)
      if (res.fragments.length > 0 && selectedId === null) {
        setSelectedId(res.fragments[0].fragment_id)
      }
    } catch {
      toast("Failed to load fragments", "error")
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { load() }, [load])

  // Clean up SSE on unmount
  useEffect(() => {
    return () => { promptEsRef.current?.close() }
  }, [])

  const handleSave = async (id: number, data: { original_text?: string; image_prompt?: string }) => {
    if (!projectId) return
    try {
      await api.updateFragment(projectId, id, data as any)
      toast("Fragment saved", "success")
      setFragments((prev) =>
        prev.map((f) => (f.fragment_id === id ? { ...f, ...data } : f))
      )
    } catch {
      toast("Failed to save fragment", "error")
    }
  }

  const handleSaveScript = async () => {
    if (!projectId) return
    setScriptSaving(true)
    try {
      await api.saveScript(projectId, scriptText)
      setScriptDirty(false)
      toast("Full script saved", "success")
    } catch {
      toast("Failed to save script", "error")
    } finally {
      setScriptSaving(false)
    }
  }

  const handleFragment = async () => {
    if (!projectId || !scriptText.trim()) return
    setFragmenting(true)
    try {
      const res = await api.fragmentScript(projectId, scriptText)
      toast(`${res.total} fragments created`, "success")
      setFragments(res.fragments)
      if (res.fragments.length > 0) {
        setSelectedId(res.fragments[0].fragment_id)
      }
    } catch (err: any) {
      toast(err?.message ?? "Failed to fragment script", "error")
    } finally {
      setFragmenting(false)
    }
  }

  const handleGeneratePrompts = async () => {
    if (!projectId) return
    
    // Count pending fragments
    const pending = fragments.filter(f => !f.image_prompt || !f.image_prompt.trim())
    if (pending.length === 0) {
      toast("All fragments already have prompts", "info")
      return
    }

    const batchSize = 5
    const totalBatchesCount = Math.ceil(pending.length / batchSize)
    setGeneratingTotal(pending.length)
    setCurrentBatch(0)
    setTotalBatches(totalBatchesCount)
    setGeneratingPrompts(true)
    setGeneratingElapsed(0)

    // Start elapsed timer
    const timerStart = Date.now()
    const timer = setInterval(() => {
      setGeneratingElapsed(Math.floor((Date.now() - timerStart) / 1000))
    }, 1000)

    // Subscribe to SSE for batch progress
    promptEsRef.current?.close()
    const es = new EventSource(api.promptEventsUrl(projectId))
    promptEsRef.current = es

    es.addEventListener("prompt_batch_complete", (e) => {
      const data = JSON.parse(e.data)
      setCurrentBatch(data.batchIndex + 1)
      // Reload fragments to show incremental updates
      api.listFragments(projectId!).then((res) => {
        setFragments(res.fragments)
      }).catch(() => {})
    })

    es.addEventListener("prompt_all_complete", () => {
      clearInterval(timer)
      setGeneratingPrompts(false)
      setGeneratingTotal(0)
      setGeneratingElapsed(0)
      setCurrentBatch(0)
      setTotalBatches(0)
      api.listFragments(projectId!).then((res) => {
        setFragments(res.fragments)
        toast(`All ${res.fragments.length} prompts generated`, "success")
      }).catch(() => {})
      es.close()
    })

    es.addEventListener("prompt_failed", (e) => {
      const data = JSON.parse(e.data)
      clearInterval(timer)
      setGeneratingPrompts(false)
      setGeneratingTotal(0)
      setGeneratingElapsed(0)
      setCurrentBatch(0)
      setTotalBatches(0)
      toast(data.error ?? "Prompt generation failed", "error")
      es.close()
    })

    // Make the generation request
    try {
      const styleToUse = imageStyle
      await api.generatePrompts(projectId, styleToUse)
      // SSE events handle the UI updates
    } catch (err: any) {
      clearInterval(timer)
      setGeneratingPrompts(false)
      setGeneratingTotal(0)
      setGeneratingElapsed(0)
      setCurrentBatch(0)
      setTotalBatches(0)
      toast(err?.message ?? "Failed to generate prompts", "error")
    }
  }

  return (
    <div>
      <PageHeader
        title={projectTitle || projectId || "Editor"}
        description="Review and edit fragments with image prompts"
        backTo="/"
        actions={
          projectId && (
            <div className="flex items-center gap-2">
              <button
                className="btn-secondary"
                onClick={handleGeneratePrompts}
                disabled={generatingPrompts || fragments.length === 0}
              >
                {generatingPrompts ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {generatingPrompts
                  ? `Generating... ${generatingElapsed}s`
                  : "Generate Prompts"}
              </button>
              <button className="btn-primary" onClick={() => navigate(`/images/${projectId}`)}>
                <ImageIcon className="w-4 h-4" />
                Generate Images
              </button>
            </div>
          )
        }
      />

      {/* Full Script Card */}
      <Card className="mb-6">
        <button
          onClick={() => setScriptOpen(!scriptOpen)}
          className="w-full flex items-center justify-between text-left"
        >
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-accent" />
            <h3 className="text-sm font-semibold text-white font-sans">Full Script</h3>
            {scriptLoading && <Loader2 className="w-3 h-3 text-gray-500 animate-spin" />}
          </div>
          {scriptOpen ? (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-500" />
          )}
        </button>

        {scriptOpen && (
          <div className="mt-4 space-y-3">
            <textarea
              className="input min-h-[300px] resize-y font-body text-sm leading-relaxed"
              placeholder="Paste the full script text here..."
              value={scriptText}
              onChange={(e) => { setScriptText(e.target.value); setScriptDirty(true) }}
              disabled={scriptLoading}
            />
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 text-xs text-gray-500 font-mono flex-wrap">
                {scriptText.length > 0 ? (
                  <>
                    <ScriptStat label="Words" value={scriptText.trim().split(/\s+/).length} />
                    <ScriptStat label="Chars" value={scriptText.length} />
                    <ScriptStat label="Lines" value={scriptText.split("\n").length} />
                    <ScriptStat
                      label="Paragraphs"
                      value={scriptText.split(/\n\s*\n/).filter(Boolean).length}
                    />
                    <ScriptStat
                      label="Sentences"
                      value={scriptText.split(/[.!?]+/).filter(s => s.trim().length > 0).length}
                    />
                    <ScriptStat
                      label="Speaking time"
                      value={`${Math.max(1, Math.round(scriptText.trim().split(/\s+/).length / 150))}m`}
                    />
                  </>
                ) : (
                  <span className="text-gray-600">No text yet</span>
                )}
              </div>
              <button
                className={`btn-primary text-xs py-1.5 px-3 transition-opacity shrink-0 ${
                  scriptDirty && !scriptSaving ? "opacity-100" : "opacity-50 pointer-events-none"
                }`}
                onClick={handleSaveScript}
                disabled={!scriptDirty || scriptSaving}
              >
                {scriptSaving ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Save className="w-3 h-3" />
                )}
                Save Script
              </button>
              <button
                className="btn-primary text-xs py-1.5 px-3 shrink-0"
                onClick={handleFragment}
                disabled={!scriptText.trim() || fragmenting}
                title="Split script into 15-21 word fragments for image prompts"
              >
                {fragmenting ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Scissors className="w-3 h-3" />
                )}
                {fragmenting ? "Fragmenting..." : "Fragment"}
              </button>
            </div>
          </div>
        )}
      </Card>

      {/* Image Style Selector */}
      <Card className="mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="w-4 h-4 text-pink-400" />
          <h3 className="text-sm font-semibold text-white font-sans">Image Style</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 font-semibold mb-1.5">Preset style</label>
            <select
              className="input w-full"
              value={customStyle ? "__custom__" : imageStyle}
              onChange={(e) => {
                if (e.target.value === "__custom__") {
                  setCustomStyle(true)
                  setImageStyle("")
                } else {
                  setCustomStyle(false)
                  setImageStyle(e.target.value)
                }
              }}
            >
              <option value="" disabled>Select style...</option>
              <optgroup label="Predefined">
                {IMAGE_STYLES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </optgroup>
              <optgroup label="Other">
                <option value="__custom__">Custom...</option>
              </optgroup>
            </select>
          </div>
          {customStyle && (
            <div>
              <label className="block text-xs text-gray-500 font-semibold mb-1.5">Custom style description</label>
              <textarea
                className="input w-full min-h-[60px] resize-none"
                placeholder="Describe el estilo visual (e.g. Cyberpunk, neon lights, 80s aesthetic...)"
                value={imageStyle}
                onChange={(e) => setImageStyle(e.target.value)}
                rows={2}
              />
            </div>
          )}
          {!customStyle && imageStyle && (
            <div className="flex items-end">
              <p className="text-xs text-gray-500 pb-2">
                Style:{' '}
                <span className="text-accent font-semibold">{imageStyle}</span>
                {' — '}
                <button
                  className="text-gray-600 hover:text-accent underline"
                  onClick={() => setCustomStyle(true)}
                >
                  Customize
                </button>
              </p>
            </div>
          )}
        </div>
      </Card>

      {/* Progress during prompt generation */}
      {generatingPrompts && (
        <Card className="mb-6 border-pink-500/30 bg-pink-500/5">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-pink-400 animate-spin shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-pink-400">
                Generating prompts for {generatingTotal} fragments
                {totalBatches > 0 && (
                  <span className="text-pink-300/70"> · Batch {currentBatch}/{totalBatches}</span>
                )}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                Elapsed: {Math.floor(generatingElapsed / 60)}m {generatingElapsed % 60}s
                {totalBatches > 0 && currentBatch > 0 && (
                  <> · ~{Math.max(1, Math.round((totalBatches - currentBatch) * 4.2))}s remaining</>
                )}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Fragments */}
      {loading ? (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-surface-card rounded-xl border border-border" />
          ))}
        </div>
      ) : (
        <FragmentList
          fragments={fragments.map((f) => ({
            fragment_id: f.fragment_id,
            original_text: f.original_text,
            image_prompt: f.image_prompt,
            status: f.status,
          }))}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onSave={handleSave}
        />
      )}
    </div>
  )
}
