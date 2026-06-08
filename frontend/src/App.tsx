import { createContext, useContext, useState } from "react"
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from "react-router-dom"
import { LayoutDashboard, FileEdit, Image, Mic, Video, Zap, Scissors, Menu } from "lucide-react"
import { ToastProvider } from "./components/Toast"
import { useActiveProject } from "./hooks/useActiveProject"
import Dashboard from "./pages/Dashboard"
import Editor from "./pages/Editor"
import Images from "./pages/Images"
import Transcribe from "./pages/Transcribe"
import Render from "./pages/Render"
import Workflow from "./pages/Workflow"
import Shorts from "./pages/Shorts"
import EmptyState from "./components/EmptyState"

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
  { to: "/transcribe", label: "Transcribe", icon: Mic },
  { to: "/render", label: "Render", icon: Video },
  { to: "/workflow", label: "Workflow", icon: Zap },
  { to: "/shorts", label: "Shorts", icon: Scissors },
]

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
      } lg:translate-x-0 fixed lg:static inset-y-0 left-0 z-30 w-56 bg-surface-card border-r border-border flex flex-col shrink-0 transition-transform duration-200`}>
        <div className="px-5 pt-5 pb-4 border-b border-border">
          <h1 className="text-lg font-bold font-sans">
            <span className="text-gradient">Workflow</span>
          </h1>
          <p className="text-[11px] text-gray-500 font-body mt-0.5 tracking-wide uppercase">
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

        <div className="px-5 py-3 border-t border-border">
          <span className="text-[11px] text-gray-600 font-mono">v0.1.0</span>
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
          className="lg:hidden flex items-center gap-2 text-sm text-gray-400 mb-4 hover:text-white transition-colors"
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
              <Route path="/editor" element={<NoProjectSelected page="Editor" icon={FileEdit} />} />
              <Route path="/images" element={<NoProjectSelected page="Images" icon={Image} />} />
              <Route path="/transcribe" element={<NoProjectSelected page="Transcribe" icon={Mic} />} />
              <Route path="/render" element={<NoProjectSelected page="Render" icon={Video} />} />
              <Route path="/workflow" element={<NoProjectSelected page="Workflow" icon={Zap} />} />
              <Route path="/shorts" element={<NoProjectSelected page="Shorts" icon={Scissors} />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ActiveProjectContext.Provider>
    </ToastProvider>
  )
}
