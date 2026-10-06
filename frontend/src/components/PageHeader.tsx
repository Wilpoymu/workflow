import type { ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

interface PageHeaderProps {
  title: string
  eyebrow?: string
  description?: string
  actions?: ReactNode
  backTo?: string
}

export default function PageHeader({ title, eyebrow, description, actions, backTo }: PageHeaderProps) {
  const navigate = useNavigate()
  return (
    <div className="relative flex items-end justify-between gap-4 mb-8 pb-5 border-b border-border animate-slide-down">
      <div className="flex items-center gap-3 min-w-0">
        {backTo && (
          <button
            onClick={() => navigate(backTo)}
            className="text-ink-faint hover:text-accent transition-colors p-1 -ml-1"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
        )}
        <div className="min-w-0">
          {eyebrow && <div className="page-eyebrow mb-2">{eyebrow}</div>}
          <h1 className="page-title text-[clamp(26px,3.2vw,40px)] truncate">{title}</h1>
          {description && (
            <p className="mt-1.5 text-[13.5px] text-ink-dim font-body">{description}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex items-center gap-3 shrink-0">{actions}</div>}
    </div>
  )
}
