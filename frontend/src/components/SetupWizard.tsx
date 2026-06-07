import { useState } from "react"
import { FolderPlus, FolderOpen, ArrowRight, AlertCircle } from "lucide-react"
import { useToast } from "./Toast"
import { api } from "../api/client"

interface SetupWizardProps {
  suggestedBase: string
  onComplete: () => void
}

export default function SetupWizard({ suggestedBase, onComplete }: SetupWizardProps) {
  const { toast } = useToast()
  const [name, setName] = useState("")
  const [basePath, setBasePath] = useState(suggestedBase)
  const [loading, setLoading] = useState(false)

  const handleCreate = async () => {
    if (!name.trim() || !basePath.trim()) return
    setLoading(true)
    try {
      await api.createChannel({ name: name.trim(), base_path: basePath.trim() })
      toast("Channel created!", "success")
      onComplete()
    } catch {
      toast("Failed to create channel", "error")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh] animate-fade-in">
      <div className="max-w-lg w-full">
        <div className="text-center mb-10">
          <div className="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mx-auto mb-5 glow-teal">
            <FolderPlus className="w-7 h-7 text-accent" />
          </div>
          <h1 className="text-2xl font-bold text-white font-sans">Welcome to Workflow</h1>
          <p className="text-sm text-gray-500 font-body mt-2 max-w-sm mx-auto leading-relaxed">
            Set up your first channel to get started. A channel is a folder where your video projects live.
          </p>
        </div>

        <div className="card space-y-5">
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 block font-sans">
              Channel Name
            </label>
            <input
              className="input"
              placeholder="e.g. My YouTube Channel"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 block font-sans">
              Projects Folder
            </label>
            <div className="relative">
              <FolderOpen className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 pointer-events-none" />
              <input
                className="input pl-10 font-mono text-xs"
                value={basePath}
                onChange={(e) => setBasePath(e.target.value)}
              />
            </div>
            <p className="text-[11px] text-gray-700 font-body mt-1.5 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              Each project (video) will be created as a subfolder here
            </p>
          </div>

          <div className="flex justify-end pt-2">
            <button
              className="btn-primary"
              onClick={handleCreate}
              disabled={loading || !name.trim() || !basePath.trim()}
            >
              {loading ? "Creating..." : "Create Channel"}
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
