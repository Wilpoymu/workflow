import { useState, useEffect } from "react"
import { Save, CheckCircle2, Clock, Sparkles } from "lucide-react"

interface FragmentListProps {
  fragments: Array<{
    fragment_id: number
    original_text: string
    image_prompt: string
    status: string
  }>
  selectedId: number | null
  onSelect: (id: number) => void
  onSave: (id: number, data: { original_text?: string; image_prompt?: string }) => void
  onRegeneratePrompt?: (fragmentId: number) => void
  generatingPrompts?: boolean
}

export default function FragmentList({ fragments, selectedId, onSelect, onSave, onRegeneratePrompt, generatingPrompts }: FragmentListProps) {
  const withPrompt = fragments.filter(f => f.image_prompt && f.image_prompt.trim())
  const pending = fragments.length - withPrompt.length

  if (fragments.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-gray-600 font-body">
        No fragments yet
      </div>
    )
  }

  return (
    <div className="flex gap-6 h-[calc(100vh-12rem)]">
      <div className="w-72 shrink-0 flex flex-col gap-2 overflow-y-auto pr-2">
        {/* Count header */}
        <div className="flex items-center gap-2 px-1 pb-1 text-xs text-gray-500 border-b border-border mb-1">
          <span className="text-green-400 font-medium">{withPrompt.length}</span>
          <span className="text-gray-600">/ {fragments.length} have prompts</span>
          {pending > 0 && (
            <span className="text-yellow-500 ml-auto">{pending} pending</span>
          )}
        </div>

        {fragments.map((f) => {
          const hasPrompt = f.image_prompt && f.image_prompt.trim()
          return (
            <button
              key={f.fragment_id}
              onClick={() => onSelect(f.fragment_id)}
              className={`text-left p-3 rounded-lg border transition-all duration-150 ${
                selectedId === f.fragment_id
                  ? "border-accent/50 bg-accent/8 shadow-[inset_2px_0_0_#2dd4bf]"
                  : hasPrompt
                    ? "border-green-500/30 bg-green-500/5 hover:border-green-500/50"
                    : "border-border bg-surface-card hover:border-accent/20"
              }`}
            >
              <span className="text-xs font-mono mb-1 block flex items-center gap-1.5">
                {hasPrompt ? (
                  <CheckCircle2 className="w-3 h-3 text-green-400 shrink-0" />
                ) : (
                  <Clock className="w-3 h-3 text-yellow-500 shrink-0" />
                )}
                <span className="text-gray-500">#{f.fragment_id}</span>
                {hasPrompt && (
                  <Sparkles className="w-3 h-3 text-pink-400/60 ml-auto" />
                )}
              </span>
              <p className="text-sm text-gray-300 line-clamp-2 font-body">
                {f.original_text}
              </p>
            </button>
          )
        })}
      </div>

      <div className="flex-1 min-w-0">
        {selectedId !== null && (
          <FragmentEditor
            key={selectedId}
            fragment={fragments.find((f) => f.fragment_id === selectedId)!}
            onSave={(data) => onSave(selectedId, data)}
            onRegeneratePrompt={onRegeneratePrompt}
            generatingPrompts={generatingPrompts}
          />
        )}
      </div>
    </div>
  )
}

function FragmentEditor({
  fragment,
  onSave,
  onRegeneratePrompt,
  generatingPrompts,
}: {
  fragment: FragmentListProps["fragments"][number]
  onSave: (data: { original_text?: string; image_prompt?: string }) => void
  onRegeneratePrompt?: (fragmentId: number) => void
  generatingPrompts?: boolean
}) {
  const [text, setText] = useState(fragment.original_text)
  const [prompt, setPrompt] = useState(fragment.image_prompt)
  const [dirty, setDirty] = useState(false)

  // Sync local state when fragment prop changes (e.g. SSE batch update)
  useEffect(() => {
    if (!dirty) {
      setText(fragment.original_text)
      setPrompt(fragment.image_prompt)
    }
  }, [fragment.fragment_id, fragment.original_text, fragment.image_prompt, dirty])

  const handleSave = () => {
    onSave({
      ...(text !== fragment.original_text ? { original_text: text } : {}),
      ...(prompt !== fragment.image_prompt ? { image_prompt: prompt } : {}),
    })
    setDirty(false)
  }

  return (
    <div className="flex flex-col gap-4 animate-fade-in">
      <div className="card">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 block font-sans">
          Fragment Text
        </label>
        <textarea
          className="input min-h-[120px] resize-y"
          value={text}
          onChange={(e) => { setText(e.target.value); setDirty(true) }}
        />
      </div>
      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider font-sans">
            Image Prompt
          </label>
          {fragment.image_prompt && fragment.image_prompt.trim() && (
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[11px] text-green-500">
                <CheckCircle2 className="w-3 h-3" />
                Generated
              </span>
              {onRegeneratePrompt && (
                <button
                  className="flex items-center gap-1 text-[10px] text-gray-600 hover:text-accent transition-colors"
                  onClick={() => onRegeneratePrompt(fragment.fragment_id)}
                  disabled={generatingPrompts}
                  title="Regenerate this prompt"
                >
                  <Sparkles className="w-3 h-3" />
                  Regenerate
                </button>
              )}
            </div>
          )}
        </div>
        <textarea
          className="input min-h-[80px] resize-y"
          value={prompt}
          onChange={(e) => { setPrompt(e.target.value); setDirty(true) }}
        />
        <div className="flex items-center justify-end mt-3">
          <button
            className={`btn-secondary text-xs py-1.5 px-3 transition-opacity ${dirty ? "opacity-100" : "opacity-0 pointer-events-none"}`}
            onClick={handleSave}
          >
            <Save className="w-3 h-3" />
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
