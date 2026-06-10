import { useEffect, useState, useCallback, useRef } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Image as ImageIcon, FileText, Save, ChevronDown, ChevronRight, Loader2, Hash, AlignLeft, TextQuote, Layers, MessageSquareText, Clock, Scissors, Sparkles, Wifi, WifiOff, Globe, Pencil, X, Check } from "lucide-react"
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

type BridgeStatus = "loading" | "connected" | "no-cookies" | "no-extension" | "error"

const LEGACY_STYLES = ["Cinematico", "Fotorrealista", "Animacion 3D", "Anime/Manga", "Arte Conceptual", "Comic", "Acuarela"]

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
  const [useGeminiWeb, setUseGeminiWeb] = useState(true)
  const [pendingSavedStyle, setPendingSavedStyle] = useState<string | null>(null)

  // Gemini Web bridge status
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus>("loading")
  const [bridgeProfiles, setBridgeProfiles] = useState(0)
  const [availableGems, setAvailableGems] = useState<Array<{ name: string; type: string; preview: string }>>([])

  // Load Gemini Web bridge status and gems
  useEffect(() => {
    const checkBridge = () => {
      api.getGeminiBridgeStatus()
        .then((data) => {
          setBridgeProfiles(data.authenticated)
          if (data.authenticated > 0) {
            setBridgeStatus("connected")
          } else if (data.total_profiles > 0) {
            setBridgeStatus("no-cookies")
          } else {
            setBridgeStatus("no-extension")
          }
        })
        .catch(() => setBridgeStatus("error"))
    }
    checkBridge()
    const interval = setInterval(checkBridge, 10000)
    return () => clearInterval(interval)
  }, [])

  // Load gems from backend
  useEffect(() => {
    api.listGems()
      .then((data) => setAvailableGems(data.gems))
      .catch(() => {})
  }, [])

  // Gem preview panel
  const [gemDetail, setGemDetail] = useState<{ name: string; type: string; value: string } | null>(null)
  const [gemDetailLoading, setGemDetailLoading] = useState(false)
  const [showFullPreview, setShowFullPreview] = useState(false)
  const [editingGem, setEditingGem] = useState(false)
  const [editGemValue, setEditGemValue] = useState("")
  const [editGemSaving, setEditGemSaving] = useState(false)

  // Fetch gem detail when style changes
  useEffect(() => {
    if (!imageStyle || customStyle) {
      setGemDetail(null)
      return
    }
    setGemDetailLoading(true)
    api.getGem(imageStyle)
      .then((d) => setGemDetail(d))
      .catch(() => setGemDetail(null))
      .finally(() => setGemDetailLoading(false))
  }, [imageStyle, customStyle])

  // Build style options from gems + legacy fallback
  const gemNames = availableGems.map((g) => g.name)
  const styleOptions = gemNames.length > 0 ? gemNames : ["Cinematico"]

  // Get gem preview for display
  const gemPreviewMap = Object.fromEntries(
    availableGems.map((g) => [g.name, g.preview])
  )

  // Get gem type for icon
  const gemTypeMap = Object.fromEntries(
    availableGems.map((g) => [g.name, g.type])
  )

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
      const savedStyle = p.prompt_style
      if (savedStyle && savedStyle !== "Cinematico") {
        setImageStyle(savedStyle)
        setPendingSavedStyle(savedStyle)
      }
    }).catch(() => {})
  }, [projectId])

  // Resolve saved style when gems finish loading (avoids race condition)
  useEffect(() => {
    if (!pendingSavedStyle) return
    if (availableGems.length === 0) return // gems not loaded yet
    const gemNames = availableGems.map((g) => g.name)
    if (!LEGACY_STYLES.includes(pendingSavedStyle) && !gemNames.includes(pendingSavedStyle)) {
      setCustomStyle(true)
    }
    setPendingSavedStyle(null)
  }, [pendingSavedStyle, availableGems])

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
      await api.generatePrompts(projectId, styleToUse, useGeminiWeb)
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

      {/* Image Style Selector + Gemini Web Status */}
      <Card className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-pink-400" />
            <h3 className="text-sm font-semibold text-white font-sans">Image Style</h3>
          </div>

          {/* Gemini Web Bridge Status + Toggle */}
          <div className="flex items-center gap-3">
            {/* Toggle switch */}
            <label className="flex items-center gap-1.5 cursor-pointer" title={useGeminiWeb ? "Gemini Web habilitado como fallback" : "Gemini Web deshabilitado"}>
              <span className={`text-[10px] font-medium ${useGeminiWeb ? 'text-green-400/70' : 'text-gray-600'}`}>GW</span>
              <div className="relative w-8 h-4 rounded-full transition-colors" style={{ backgroundColor: useGeminiWeb ? '#22c55e' : '#404040' }}>
                <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${useGeminiWeb ? 'translate-x-4' : 'translate-x-0.5'}`} />
              </div>
              <input type="checkbox" className="hidden" checked={useGeminiWeb} onChange={(e) => setUseGeminiWeb(e.target.checked)} />
            </label>

            {/* Status indicator */}
            <div className="flex items-center gap-1.5 text-xs" title="Gemini Web cookie-based provider status">
              {bridgeStatus === "connected" ? (
                <>
                  <Wifi className="w-3.5 h-3.5 text-green-400" />
                  <span className="text-green-400 font-medium">Gemini Web</span>
                  <span className="text-green-400/60">({bridgeProfiles} acc.)</span>
                </>
              ) : bridgeStatus === "no-cookies" ? (
                <>
                  <Globe className="w-3.5 h-3.5 text-yellow-400" />
                  <span className="text-yellow-400">Gemini Web</span>
                  <span className="text-yellow-400/60">sin cookies</span>
                </>
              ) : bridgeStatus === "no-extension" ? (
                <>
                  <WifiOff className="w-3.5 h-3.5 text-gray-500" />
                  <span className="text-gray-500">Gemini Web</span>
                  <span className="text-gray-500/60">ext. no detectada</span>
                </>
              ) : bridgeStatus === "loading" ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 text-gray-500 animate-spin" />
                  <span className="text-gray-500">Gemini Web</span>
                </>
              ) : (
                <>
                  <WifiOff className="w-3.5 h-3.5 text-red-400" />
                  <span className="text-red-400">Gemini Web</span>
                  <span className="text-red-400/60">error</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 font-semibold mb-1.5">
              Visual style / Gem
              {imageStyle && gemPreviewMap[imageStyle] && (
                <span className="text-gray-600 font-normal ml-2">
                  — preview: {gemPreviewMap[imageStyle]}
                </span>
              )}
            </label>
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
              <optgroup label="Estilos disponibles">
                {styleOptions.map((s) => {
                  const type = gemTypeMap[s] || "style"
                  const icon = type === "prompt" ? "📝" : "🎨"
                  return (
                    <option key={s} value={s} title={type === "prompt" ? "Prompt maestro - instrucciones completas" : "Descriptor de estilo visual"}>
                      {icon} {s}
                    </option>
                  )
                })}
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

        {/* Gem Preview Panel (editable) */}
        {gemDetailLoading ? (
          <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
            <Loader2 className="w-3 h-3 animate-spin" />
            Loading gem details...
          </div>
        ) : gemDetail && !customStyle ? (
          <div className="mt-3 border border-border rounded-lg bg-surface-card overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-border">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  {gemDetail.type === "prompt" ? "Prompt Maestro" : "Estilo Visual"}
                </span>
                <span className="text-[10px] text-gray-600 font-mono">
                  {gemDetail.type === "prompt" ? "system prompt" : "descriptor"}
                </span>
              </div>
              {editingGem ? (
                <div className="flex items-center gap-1">
                  <button
                    className="p-1 rounded hover:bg-surface-hover text-green-400 disabled:opacity-40"
                    onClick={async () => {
                      if (!editGemValue.trim()) return
                      setEditGemSaving(true)
                      try {
                        await api.updateGem(imageStyle, { value: editGemValue })
                        setGemDetail({ ...gemDetail, value: editGemValue })
                        setEditingGem(false)
                        // Refresh gem list to update previews
                        api.listGems().then((d) => setAvailableGems(d.gems)).catch(() => {})
                      } catch { /* ignore */ }
                      setEditGemSaving(false)
                    }}
                    disabled={editGemSaving}
                    title="Save"
                  >
                    {editGemSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    className="p-1 rounded hover:bg-surface-hover text-gray-500"
                    onClick={() => setEditingGem(false)}
                    title="Cancel"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <button
                  className="p-1 rounded hover:bg-surface-hover text-gray-500 hover:text-accent"
                  onClick={() => { setEditGemValue(gemDetail.value); setEditingGem(true); setShowFullPreview(true) }}
                  title="Edit gem content"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Content */}
            {editingGem ? (
              <textarea
                className="w-full px-3 py-2 text-xs font-mono leading-relaxed bg-[#0a0a0a] text-gray-300 border-0 resize-y min-h-[120px] focus:outline-none"
                value={editGemValue}
                onChange={(e) => setEditGemValue(e.target.value)}
                autoFocus
              />
            ) : (
              <pre className={`px-3 py-2 text-xs font-mono leading-relaxed text-gray-400 overflow-x-auto whitespace-pre-wrap ${
                showFullPreview ? "" : "max-h-20 overflow-y-hidden"
              }`}>
                {gemDetail.value}
              </pre>
            )}

            {/* Expand/collapse (only when not editing) */}
            {!editingGem && gemDetail.value.length > 200 && (
              <button
                className="w-full px-3 py-1.5 text-xs text-accent hover:text-accent-light border-t border-border font-medium"
                onClick={() => setShowFullPreview(!showFullPreview)}
              >
                {showFullPreview ? "Show less ▲" : `Show more (${gemDetail.value.length} chars) ▼`}
              </button>
            )}
          </div>
        ) : null}
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
