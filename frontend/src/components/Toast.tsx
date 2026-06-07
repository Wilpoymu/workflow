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
  success: { border: "border-emerald-500/30", icon: "text-emerald-400", bar: "bg-emerald-500" },
  error: { border: "border-red-500/30", icon: "text-red-400", bar: "bg-red-500" },
  info: { border: "border-sky-500/30", icon: "text-sky-400", bar: "bg-sky-500" },
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
              className={`pointer-events-auto flex items-start gap-3 min-w-80 max-w-sm
                bg-surface-elevated/95 backdrop-blur-sm border ${c.border} rounded-lg p-4
                shadow-2xl animate-slide-up`}
            >
              <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${c.icon}`} />
              <p className="text-sm text-gray-300 font-body">{t.message}</p>
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
