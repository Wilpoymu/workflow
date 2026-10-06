import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from "react"
import { CheckCircle, XCircle, Info } from "lucide-react"

interface ToastData {
  id: number
  message: string
  type: "success" | "error" | "info"
}

interface ToastCtx {
  toast: (message: string, type?: ToastData["type"]) => void
}

const ToastContext = createContext<ToastCtx>({ toast: () => {} })

export function useToast() {
  return useContext(ToastContext)
}

const icons = {
  success: CheckCircle,
  error: XCircle,
  info: Info,
}

const config = {
  success: { border: "border-ok/30", icon: "text-ok", bar: "bg-ok" },
  error: { border: "border-danger/30", icon: "text-danger", bar: "bg-danger" },
  info: { border: "border-tag-blue/30", icon: "text-tag-blue", bar: "bg-tag-blue" },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastData[]>([])
  const counter = useRef(0)

  const toast = useCallback((message: string, type: ToastData["type"] = "info") => {
    const id = ++counter.current
    setToasts((prev) => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3500)
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => {
          const Icon = icons[t.type]
          const c = config[t.type]
          return (
            <div
              key={t.id}
              className={`pointer-events-auto relative overflow-hidden flex items-start gap-3 min-w-80 max-w-sm
                bg-surface-elevated/95 backdrop-blur-sm border ${c.border} rounded-[12px] p-4
                shadow-[0_30px_60px_-30px_rgba(0,0,0,0.95)] animate-slide-up`}
            >
              <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${c.icon}`} />
              <p className="text-sm text-ink-dim font-body">{t.message}</p>
              <div className={`absolute bottom-0 left-0 h-0.5 ${c.bar} rounded-full animate-[shrink_3.5s_linear]`}
                style={{ width: "100%" }}
              />
            </div>
          )
        })}
      </div>
      <style>{`
        @keyframes shrink {
          from { width: 100%; }
          to { width: 0%; }
        }
      `}</style>
    </ToastContext.Provider>
  )
}
