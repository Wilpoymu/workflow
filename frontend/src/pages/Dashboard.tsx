import { useEffect, useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import {
  Plus, FolderOpen, Play, ArrowRight, LayoutGrid,
  Image, Mic, Video, Zap, FileEdit
} from "lucide-react"
import PageHeader from "../components/PageHeader"
import Card from "../components/Card"
import Badge from "../components/Badge"
import EmptyState from "../components/EmptyState"
import Modal from "../components/Modal"
import SetupWizard from "../components/SetupWizard"
import { useToast } from "../components/Toast"
import { api } from "../api/client"
import { useActiveProjectContext } from "../App"
import type { Channel, ProjectRow } from "../types"

const pipelineSteps = [
  { label: "Editor", desc: "Split script & prompts", icon: FileEdit, page: "editor" },
  { label: "Images", desc: "Generate scene images", icon: Image, page: "images" },
  { label: "Transcribe", desc: "Whisper transcription", icon: Mic, page: "transcribe" },
  { label: "Render", desc: "Ken Burns output", icon: Video, page: "render" },
]

const statusMap: Record<string, { variant: "success" | "warning" | "info"; label: string }> = {
  active: { variant: "success", label: "Active" },
  editing: { variant: "warning", label: "Editing" },
  done: { variant: "info", label: "Done" },
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { setActiveProject } = useActiveProjectContext()

  const [loading, setLoading] = useState(true)
  const [setup, setSetup] = useState<{ has_channels: boolean; suggested_base: string } | null>(null)
  const [channels, setChannels] = useState<Channel[]>([])
  const [activeChannel, setActiveChannel] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectRow[]>([])

  const [showCreateProject, setShowCreateProject] = useState(false)
  const [showCreateChannel, setShowCreateChannel] = useState(false)
  const [projectTopic, setProjectTopic] = useState("")
  const [newProjectTitle, setNewProjectTitle] = useState("")
  const [newChannelName, setNewChannelName] = useState("")
  const [newChannelPath, setNewChannelPath] = useState("")

  const loadAll = async () => {
    try {
      const s = await api.setupStatus()
      setSetup(s)

      if (s.has_channels) {
        const ch = await api.listChannels()
        setChannels(ch.channels)
        const firstId = ch.channels[0]?.id ?? null
        setActiveChannel((prev) => prev ?? firstId)
      }
    } catch {
      toast("Failed to load workspace", "error")
    } finally {
      setLoading(false)
    }
  }

  const loadProjects = async (channelId: string) => {
    try {
      const res = await api.listProjects(channelId)
      setProjects(res.projects)
    } catch {
      toast("Failed to load projects", "error")
    }
  }

  useEffect(() => { loadAll() }, [])

  useEffect(() => {
    if (activeChannel) loadProjects(activeChannel)
  }, [activeChannel])

  const goToProject = (projectId: string, page: string) => {
    setActiveProject(projectId)
    navigate(`/${page}/${projectId}`)
  }

  const goToPipelineStep = (page: string) => {
    if (projects.length > 0) {
      goToProject(projects[0].id, page)
    } else {
      navigate(`/${page}`)
    }
  }

  const newProjectName = useMemo(() => {
    if (!projectTopic.trim()) return ""
    const slug = projectTopic.trim().toLowerCase().replace(/\s+/g, "-")
    const now = new Date()
    const months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    const month = months[now.getMonth()]
    const year = now.getFullYear()
    return `${slug}-${month}-${year}`
  }, [projectTopic])

  const handleCreateProject = async () => {
    if (!newProjectName.trim() || !activeChannel) return
    try {
      await api.createProject({ name: newProjectName.trim(), title: newProjectTitle.trim() || undefined, channel_id: activeChannel })
      toast("Project created", "success")
      setShowCreateProject(false)
      setProjectTopic("")
      setNewProjectTitle("")
      loadProjects(activeChannel)
    } catch {
      toast("Failed to create project", "error")
    }
  }

  const handleCreateChannel = async () => {
    if (!newChannelName.trim() || !newChannelPath.trim()) return
    try {
      await api.createChannel({ name: newChannelName.trim(), base_path: newChannelPath.trim() })
      toast("Channel created", "success")
      setShowCreateChannel(false)
      setNewChannelName("")
      setNewChannelPath("")
      await loadAll()
    } catch {
      toast("Failed to create channel", "error")
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-600 font-body mt-8">Loading workspace...</p>
  }

  if (setup && !setup.has_channels) {
    return <SetupWizard suggestedBase={setup.suggested_base} onComplete={loadAll} />
  }

  const activeChannelObj = channels.find((c) => c.id === activeChannel)

  return (
    <div>
      <PageHeader
        title={activeChannelObj?.name ?? "Dashboard"}
        description="Manage your video production projects"
        actions={
          <div className="flex items-center gap-2">
            <button className="btn-secondary text-xs" onClick={() => {
              setNewChannelPath(setup?.suggested_base ?? "")
              setShowCreateChannel(true)
            }}>
              <Plus className="w-3.5 h-3.5" />
              Channel
            </button>
            <button className="btn-primary" onClick={() => setShowCreateProject(true)}>
              <Plus className="w-4 h-4" />
              New Project
            </button>
          </div>
        }
      />

      {/* Channel Tabs */}
      <div className="flex items-center gap-1 mb-8 p-1 bg-surface-card rounded-lg border border-border w-fit overflow-x-auto max-w-full">
        {channels.map((ch) => (
          <button
            key={ch.id}
            onClick={() => setActiveChannel(ch.id)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-150 ${
              activeChannel === ch.id
                ? "bg-accent/10 text-accent shadow-sm"
                : "text-gray-500 hover:text-gray-300 hover:bg-surface-hover"
            }`}
          >
            <LayoutGrid className="w-3.5 h-3.5" />
            {ch.name}
          </button>
        ))}
      </div>

      {/* Pipeline */}
      <section className="mb-10">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4 font-sans">
          Pipeline
        </h2>
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {pipelineSteps.map((step, i) => {
            const Icon = step.icon
            return (
              <div key={step.label} className="flex items-center gap-2 flex-1 min-w-0">
                <button
                  onClick={() => goToPipelineStep(step.page)}
                  className="flex-1 min-w-0 text-left"
                >
                  <Card className="flex items-center gap-4 py-3 px-4 card-hover">
                    <Icon className="w-5 h-5 text-accent shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-white">{step.label}</p>
                      <p className="text-xs text-gray-600 font-body">{step.desc}</p>
                    </div>
                  </Card>
                </button>
                {i < pipelineSteps.length - 1 && (
                  <ArrowRight className="w-4 h-4 text-gray-700 shrink-0" />
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Projects */}
      <section>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4 font-sans">
          Projects
        </h2>

        {projects.length === 0 ? (
          <EmptyState
            icon={<FolderOpen />}
            title="No projects in this channel"
            description="Create your first video project"
            action={
              <button className="btn-primary" onClick={() => setShowCreateProject(true)}>
                <Plus className="w-4 h-4" />New Project
              </button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((p) => {
              const s = statusMap[p.status] ?? { variant: "default", label: p.status }
              return (
                <Card key={p.id} className="animate-fade-in card-hover">
                  <div
                    className="cursor-pointer"
                    onClick={() => goToProject(p.id, "editor")}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <h3 className="font-semibold text-white font-sans">{p.name}</h3>
                      <Badge variant={s.variant}>{s.label}</Badge>
                    </div>
                    <p className="text-xs text-gray-600 font-body mb-4">
                      Created {new Date(p.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="pt-3 border-t border-border flex items-center gap-1">
                    <button
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs text-gray-500 hover:text-accent hover:bg-accent/5 transition-all"
                      onClick={() => goToProject(p.id, "editor")}
                    >
                      <Play className="w-3 h-3" /> Editor
                    </button>
                    <button
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs text-gray-500 hover:text-accent hover:bg-accent/5 transition-all"
                      onClick={() => goToProject(p.id, "images")}
                    >
                      <Image className="w-3 h-3" /> Images
                    </button>
                    <button
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs text-gray-500 hover:text-accent hover:bg-accent/5 transition-all"
                      onClick={() => goToProject(p.id, "transcribe")}
                    >
                      <Mic className="w-3 h-3" /> Audio
                    </button>
                    <button
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs text-gray-500 hover:text-accent hover:bg-accent/5 transition-all"
                      onClick={() => goToProject(p.id, "render")}
                    >
                      <Video className="w-3 h-3" /> Render
                    </button>
                    <button
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs text-gray-500 hover:text-accent hover:bg-accent/5 transition-all"
                      onClick={() => goToProject(p.id, "workflow")}
                    >
                      <Zap className="w-3 h-3" /> Run
                    </button>
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </section>

      {/* Create Project Modal */}
      <Modal open={showCreateProject} onClose={() => setShowCreateProject(false)} title="New Project">
        <div className="flex flex-col gap-4">
          <div>
            <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">Channel</label>
            <select className="input" value={activeChannel ?? ""} disabled={channels.length <= 1}>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.id}>{ch.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">Project Topic *</label>
            <input
              className="input"
              placeholder="e.g. Libra, Aries, Meditacion"
              value={projectTopic}
              onChange={(e) => setProjectTopic(e.target.value)}
              autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") handleCreateProject() }}
            />
            {newProjectName && (
              <p className="text-xs text-gray-600 mt-1.5 font-mono">
                Will create: <span className="text-accent">{newProjectName}</span>
              </p>
            )}
          </div>
          <div>
            <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">Display Title (optional)</label>
            <input
              className="input"
              placeholder="e.g. Horóscopo Libra Junio 2026"
              value={newProjectTitle}
              onChange={(e) => setNewProjectTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreateProject() }}
            />
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <button className="btn-secondary" onClick={() => setShowCreateProject(false)}>Cancel</button>
            <button className="btn-primary" onClick={handleCreateProject} disabled={!projectTopic.trim()}>
              <Plus className="w-4 h-4" />Create
            </button>
          </div>
        </div>
      </Modal>

      {/* Create Channel Modal */}
      <Modal open={showCreateChannel} onClose={() => setShowCreateChannel(false)} title="New Channel">
        <div className="flex flex-col gap-4">
          <div>
            <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">Channel Name *</label>
            <input
              className="input"
              placeholder="e.g. My YouTube Channel"
              value={newChannelName}
              onChange={(e) => setNewChannelName(e.target.value)}
              autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") handleCreateChannel() }}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 font-medium block mb-1.5 font-sans">Projects Folder *</label>
            <input
              className="input font-mono text-xs"
              placeholder="e.g. C:\Users\...\Youtube\canal"
              value={newChannelPath}
              onChange={(e) => setNewChannelPath(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreateChannel() }}
            />
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <button className="btn-secondary" onClick={() => setShowCreateChannel(false)}>Cancel</button>
            <button className="btn-primary" onClick={handleCreateChannel} disabled={!newChannelName.trim() || !newChannelPath.trim()}>
              <Plus className="w-4 h-4" />Create
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
