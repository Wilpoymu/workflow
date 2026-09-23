import { createContext, useContext, useState } from "react"
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom"
import { LayoutDashboard, FileEdit, Image, ImageDown, Mic, Video, Zap, Scissors, FolderOpen, Menu, Hash, Sparkles } from "lucide-react"
import { ToastProvider } from "./components/Toast"
import { useActiveProject } from "./hooks/useActiveProject"
import Dashboard from "./pages/Dashboard"
import Editor from "./pages/Editor"
import Images from "./pages/Images"
import Transcribe from "./pages/Transcribe"
import Render from "./pages/Render"
import Workflow from "./pages/Workflow"
import Shorts from "./pages/Shorts"
import ShortsMetadata from "./pages/ShortsMetadata"
import ShortsMetadataList from "./pages/ShortsMetadataList"
import VideoMetadata from "./pages/VideoMetadata"
import Thumbnails from "./pages/Thumbnails"
import Timeline from "./pages/Timeline"
import EmptyState from "./components/EmptyState"
import { api } from "./api/client"

const ActiveProjectContext = createContext<{
  activeProject: string | null
  setActiveProject: (id: string | null) => void
}>({ activeProject: null, setActiveProject: () => {} })

export function useActiveProjectContext() {
  return useContext(ActiveProjectContext)
}

function NoProjectSelected({ page, icon: Icon }: { page: string; icon: React.ComponentType<{ className?: string }> }) {
  const navigate = useNavigate()
  return (
    <EmptyState
      icon={<Icon />}
      title={`No project selected for ${page}`}
      description="Select a project from the Dashboard to access this page"
      action={
        <button className="btn-primary" onClick={() => navigate("/")}>
          <LayoutDashboard className="w-4 h-4" />
          Go to Dashboard
        </button>
      }
    />
  )
}

const navGroups = [
  {
    label: "Pipeline",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/editor", label: "Editor", icon: FileEdit },
      { to: "/images", label: "Images", icon: Image },
      { to: "/thumbnails", label: "Thumbnail", icon: ImageDown },
      { to: "/transcribe", label: "Transcribe", icon: Mic },
      { to: "/render", label: "Render", icon: Video },
      { to: "/workflow", label: "Workflow", icon: Zap },
    ],
  },
  {
    label: "Shorts & SEO",
    items: [
      { to: "/shorts", label: "Shorts", icon: Scissors },
      { to: "/shorts-metadata", label: "Metadata", icon: Hash },
      { to: "/metadata/shorts", label: "Shorts SEO", icon: Hash },
      { to: "/metadata", label: "Video SEO", icon: Sparkles },
    ],
  },
]

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activeProject } = useActiveProjectContext()
  const navigate = useNavigate()
  const location = useLocation()

  const isActive = (base: string) => {
    const path = location.pathname
    if (base === "/") return path === "/"
    const candidates = navGroups
      .flatMap((g) => g.items.map((i) => i.to))
      .filter((b) => b !== "/")
    const match = candidates
      .filter((b) => path === b || path.startsWith(b + "/"))
      .sort((a, b) => b.length - a.length)[0]
    return match === base
  }

  const handleClick = (base: string) => {
    if (base === "/") {
      navigate("/")
    } else if (activeProject) {
      navigate(`${base}/${activeProject}`)
    } else {
      navigate("/")
    }
    onClose()
  }

  return (
    <>
      {open && (
        <div className="fixed inset-0 bg-black/50 z-20 lg:hidden" onClick={onClose} />
      )}
      <aside className={`${
        open ? "translate-x-0" : "-translate-x-full"
      } lg:translate-x-0 fixed lg:static inset-y-0 left-0 z-30 w-64 bg-surface-card border-r border-border flex flex-col shrink-0 transition-transform duration-200`}>
        <div className="px-5 pt-5 pb-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 shrink-0 rounded-[10px] border border-border flex items-center justify-center font-mono font-bold text-accent bg-gradient-to-b from-accent/15 to-transparent">
              W
            </div>
            <div className="min-w-0">
              <h1 className="font-serif font-normal text-[21px] leading-none text-ink">Workflow</h1>
              <p className="font-mono text-[9px] text-ink-faint mt-1 tracking-[0.2em] uppercase truncate">
                Video pipeline
              </p>
            </div>
          </div>
        </div>

        <nav className="flex-1 flex flex-col p-3 overflow-y-auto">
          {navGroups.map((group) => (
            <div key={group.label}>
              <div className="nav-group-label flex items-center gap-2.5 mx-3 mt-5 mb-2 after:content-[''] after:h-px after:flex-1 after:bg-border">
                {group.label}
              </div>
              <div className="flex flex-col gap-0.5">
                {group.items.map(({ to, label, icon: Icon }) => (
                  <button
                    key={to}
                    onClick={() => handleClick(to)}
                    className={`nav-link ${isActive(to) ? "nav-link-active" : ""}`}
                  >
                    <Icon className="w-4 h-4" />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="p-3 border-t border-border">
          <button
            onClick={() => activeProject && api.openFolder(activeProject)}
            disabled={!activeProject}
            className="flex items-center justify-center gap-2 w-full px-3 py-2.5 rounded-lg border border-dashed border-border text-ink-faint hover:text-accent hover:border-accent/50 hover:bg-accent/5 transition-all font-mono text-[10px] tracking-[0.12em] uppercase disabled:opacity-30 disabled:pointer-events-none"
          >
            <FolderOpen className="w-3.5 h-3.5" />
            Open project folder
          </button>
        </div>
      </aside>
    </>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="h-dvh flex bg-surface overflow-hidden">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main className="flex-1 overflow-y-auto p-6 lg:p-8">
        <button
          className="lg:hidden flex items-center gap-2 text-sm text-ink-dim mb-4 hover:text-ink transition-colors"
          onClick={() => setSidebarOpen(true)}
        >
          <Menu className="w-5 h-5" />
          Menu
        </button>
        {children}
      </main>
    </div>
  )
}

export default function App() {
  const { activeProject, setActiveProject } = useActiveProject()

  return (
    <ToastProvider>
      <ActiveProjectContext.Provider value={{ activeProject, setActiveProject }}>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/editor/:projectId" element={<Editor />} />
              <Route path="/images/:projectId" element={<Images />} />
              <Route path="/transcribe/:projectId" element={<Transcribe />} />
              <Route path="/render/:projectId" element={<Render />} />
              <Route path="/workflow/:projectId" element={<Workflow />} />
              <Route path="/shorts/:projectId" element={<Shorts />} />
              <Route path="/shorts-metadata/:projectId" element={<ShortsMetadata />} />
              <Route path="/metadata/shorts/:projectId" element={<ShortsMetadataList />} />
              <Route path="/metadata/:projectId" element={<VideoMetadata />} />
              <Route path="/thumbnails/:projectId" element={<Thumbnails />} />
              <Route path="/timeline/:projectId" element={<Timeline />} />
              <Route path="/editor" element={<NoProjectSelected page="Editor" icon={FileEdit} />} />
              <Route path="/images" element={<NoProjectSelected page="Images" icon={Image} />} />
              <Route path="/transcribe" element={<NoProjectSelected page="Transcribe" icon={Mic} />} />
              <Route path="/render" element={<NoProjectSelected page="Render" icon={Video} />} />
              <Route path="/workflow" element={<NoProjectSelected page="Workflow" icon={Zap} />} />
              <Route path="/shorts" element={<NoProjectSelected page="Shorts" icon={Scissors} />} />
              <Route path="/shorts-metadata" element={<NoProjectSelected page="Shorts Metadata" icon={Hash} />} />
              <Route path="/metadata/shorts" element={<NoProjectSelected page="Shorts SEO" icon={Hash} />} />
              <Route path="/metadata" element={<NoProjectSelected page="Video SEO" icon={Sparkles} />} />
              <Route path="/thumbnails" element={<NoProjectSelected page="Thumbnail" icon={ImageDown} />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ActiveProjectContext.Provider>
    </ToastProvider>
  )
}
