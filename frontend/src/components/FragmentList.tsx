import { useState } from "react"
import { Save } from "lucide-react"

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
}

export default function FragmentList({ fragments, selectedId, onSelect, onSave }: FragmentListProps) {
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
        {fragments.map((f) => (
          <button
            key={f.fragment_id}
            onClick={() => onSelect(f.fragment_id)}
            className={`text-left p-3 rounded-lg border transition-all duration-150 ${
              selectedId === f.fragment_id
                ? "border-accent/50 bg-accent/8 shadow-[inset_2px_0_0_#2dd4bf]"
                : "border-border bg-surface-card hover:border-accent/20"
            }`}
          >
            <span className="text-xs font-mono text-gray-600 mb-1 block">
              #{f.fragment_id} · <span className={f.status === "generated" ? "text-emerald-500" : "text-gray-600"}>{f.status}</span>
            </span>
            <p className="text-sm text-gray-300 line-clamp-2 font-body">
              {f.original_text}
            </p>
          </button>
        ))}
      </div>

      <div className="flex-1 min-w-0">
        {selectedId !== null && (
          <FragmentEditor
            key={selectedId}
            fragment={fragments.find((f) => f.fragment_id === selectedId)!}
            onSave={(data) => onSave(selectedId, data)}
          />
        )}
      </div>
    </div>
  )
}

function FragmentEditor({
  fragment,
  onSave,
}: {
  fragment: FragmentListProps["fragments"][number]
  onSave: (data: { original_text?: string; image_prompt?: string }) => void
}) {
  const [text, setText] = useState(fragment.original_text)
  const [prompt, setPrompt] = useState(fragment.image_prompt)
  const [dirty, setDirty] = useState(false)

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
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 block font-sans">
          Image Prompt
        </label>
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
