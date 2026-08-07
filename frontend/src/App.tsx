import { createContext, useContext, useState } from "react"
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from "react-router-dom"
import { LayoutDashboard, FileEdit, Image, ImageDown, Mic, Video, Zap, Scissors, FolderOpen, Menu, Hash, Sparkles } from "lucide-react"
import { ToastProvider } from "./components/Toast"
import { ThemeToggle } from "./components/ThemeToggle"
import { useActiveProject } from "./hooks/useActiveProject"
import Dashboard from "./pages/Dashboard"
import Editor from "./pages/Editor"
import Images from "./pages/Images"
import Transcribe from "./pages/Transcribe"
import Render from "./pages/Render"
import TimelinePage from "./pages/Timeline"
import Workflow from "./pages/Workflow"
import Shorts from "./pages/Shorts"
import ShortsMetadata from "./pages/ShortsMetadata"
import ShortsMetadataList from "./pages/ShortsMetadataList"
import VideoMetadata from "./pages/VideoMetadata"
import Thumbnails from "./pages/Thumbnails"
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

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/editor", label: "Editor", icon: FileEdit },
  { to: "/images", label: "Images", icon: Image },
  { to: "/thumbnails", label: "Thumbnail", icon: ImageDown },
  { to: "/transcribe", label: "Transcribe", icon: Mic },
  { to: "/render", label: "Render", icon: Video },
  { to: "/timeline", label: "Timeline", icon: Video },
  { to: "/workflow", label: "Workflow", icon: Zap },
  { to: "/shorts", label: "Shorts", icon: Scissors },
  { to: "/shorts-metadata", label: "Metadata", icon: Hash },
  { to: "/metadata/shorts", label: "Shorts SEO", icon: Hash },
  { to: "/metadata", label: "Video SEO", icon: Sparkles },
]

function WorkflowLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} xmlns="http://www.w3.org/2000/svg">
      <g transform="translate(4, 6)">
        <path
          d="M 2 10 C 2 6, 5 4, 8 5 C 11 6, 10 10, 13 9 C 16 8, 15 4, 18 5 C 21 6, 20 10, 16 10 L 2 10 Z"
          fill="currentColor"
          opacity="0.95"
        />
        <circle cx="17" cy="7" r="1.2" fill="currentColor" />
      </g>
    </svg>
  )
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activeProject } = useActiveProjectContext()
  const navigate = useNavigate()
  const location = useLocation()

  const isActive = (base: string) => {
    if (base === "/") return location.pathname === "/"
    return location.pathname.startsWith(base)
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
      } lg:translate-x-0 fixed lg:static inset-y-0 left-0 z-30 w-56 bg-surface-card dark:bg-[#0a0a14] border-r border-border flex flex-col shrink-0 transition-transform duration-200`}>
        <div className="px-5 pt-5 pb-4 border-b border-border">
          <div className="flex items-center gap-2.5">
            <WorkflowLogo className="w-6 h-6 text-foreground" />
            <h1 className="text-lg font-bold font-sans">
              <span className="text-gradient">Workflow</span>
            </h1>
          </div>
          <p className="text-[11px] text-foreground-tertiary font-body mt-0.5 tracking-wide uppercase">
            Video Production Pipeline
          </p>
        </div>

        <nav className="flex-1 flex flex-col gap-1 p-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <button
              key={to}
              onClick={() => handleClick(to)}
              className={`nav-link ${isActive(to) ? "nav-link-active" : ""}`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </nav>

        <div className="border-t border-border">
          <div className="flex items-center justify-between px-3 py-2">
            <button
              onClick={() => activeProject && api.openFolder(activeProject)}
              disabled={!activeProject}
              className="flex items-center gap-2 flex-1 px-2 py-1.5 text-xs text-foreground-secondary hover:text-accent hover:bg-surface-hover rounded-lg transition-colors disabled:opacity-30 disabled:pointer-events-none"
            >
              <FolderOpen className="w-3.5 h-3.5" />
              Open Project Folder
            </button>
            <ThemeToggle />
          </div>
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
          className="lg:hidden flex items-center gap-2 text-sm text-foreground-tertiary mb-4 hover:text-foreground transition-colors"
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
               <Route path="/timeline/:projectId" element={<TimelinePage />} />
               <Route path="/workflow/:projectId" element={<Workflow />} />
              <Route path="/shorts/:projectId" element={<Shorts />} />
              <Route path="/shorts-metadata/:projectId" element={<ShortsMetadata />} />
              <Route path="/metadata/shorts/:projectId" element={<ShortsMetadataList />} />
              <Route path="/metadata/:projectId" element={<VideoMetadata />} />
              <Route path="/thumbnails/:projectId" element={<Thumbnails />} />
              <Route path="/editor" element={<NoProjectSelected page="Editor" icon={FileEdit} />} />
              <Route path="/images" element={<NoProjectSelected page="Images" icon={Image} />} />
              <Route path="/transcribe" element={<NoProjectSelected page="Transcribe" icon={Mic} />} />
               <Route path="/render" element={<NoProjectSelected page="Render" icon={Video} />} />
               <Route path="/timeline" element={<NoProjectSelected page="Timeline" icon={Video} />} />
               <Route path="/workflow" element={<NoProjectSelected page="Workflow" icon={Zap} />} />
              <Route path="/shorts" element={<NoProjectSelected page="Shorts" icon={Scissors} />} />
              <Route path="/shorts-metadata" element={<NoProjectSelected page="Shorts Metadata" icon={Hash} />} />
              <Route path="/metadata/shorts" element={<NoProjectSelected page="Shorts SEO" icon={Hash} />} />
              <Route path="/metadata" element={<NoProjectSelected page="Video SEO" icon={Sparkles} />} />
              <Route path="/thumbnails" element={<NoProjectSelected page="Thumbnail" icon={ImageDown} />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ActiveProjectContext.Provider>
    </ToastProvider>
  )
}
