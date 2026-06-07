import { useEffect, useState, useCallback } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Image as ImageIcon } from "lucide-react"
import PageHeader from "../components/PageHeader"
import FragmentList from "../components/FragmentList"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type { Fragment as FragmentType } from "../types"

export default function Editor() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()
  const [fragments, setFragments] = useState<FragmentType[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [projectTitle, setProjectTitle] = useState("")

  useEffect(() => {
    if (projectId) setActiveProject(projectId)
  }, [projectId, setActiveProject])

  useEffect(() => {
    if (!projectId) return
    api.getProject(projectId).then((p) => {
      setProjectTitle(p.title || p.name)
    }).catch(() => {})
  }, [projectId])

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

  return (
    <div>
      <PageHeader
        title={projectTitle || projectId || "Editor"}
        description="Review and edit fragments with image prompts"
        backTo="/"
        actions={
          projectId && (
            <button className="btn-primary" onClick={() => navigate(`/images/${projectId}`)}>
              <ImageIcon className="w-4 h-4" />
              Generate Images
            </button>
          )
        }
      />

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
