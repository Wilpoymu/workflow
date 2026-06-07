import { useCallback, useState } from "react"
import { Upload } from "lucide-react"

interface DropZoneProps {
  accept?: string
  multiple?: boolean
  label: string
  hint?: string
  onFiles: (files: File[]) => void
}

export default function DropZone({ accept, multiple, label, hint, onFiles }: DropZoneProps) {
  const [dragging, setDragging] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length) onFiles(files)
    },
    [onFiles]
  )

  return (
    <div
      className={`relative flex flex-col items-center justify-center gap-3
        border-2 border-dashed rounded-xl p-10 text-center cursor-pointer
        transition-all duration-200
        ${dragging
          ? "border-accent bg-accent/8 glow-teal-sm"
          : "border-border hover:border-accent/30 hover:bg-surface-hover/50"
        }`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => {
        const input = document.createElement("input")
        input.type = "file"
        input.accept = accept ?? ""
        input.multiple = multiple ?? false
        input.onchange = () => {
          if (input.files) onFiles(Array.from(input.files))
        }
        input.click()
      }}
    >
      <div className={`p-3 rounded-full transition-colors duration-200
        ${dragging ? "bg-accent/15 text-accent" : "bg-surface-hover text-gray-500"}`}
      >
        <Upload className="w-6 h-6" />
      </div>
      <div>
        <p className="text-sm font-medium text-gray-300">{label}</p>
        {hint && <p className="mt-1 text-xs text-gray-600">{hint}</p>}
      </div>
    </div>
  )
}
