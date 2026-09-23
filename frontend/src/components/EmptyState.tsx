import type { ReactNode } from "react"

interface EmptyStateProps {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

export default function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center animate-fade-in">
      <div className="w-14 h-14 rounded-full border border-dashed border-border flex items-center justify-center text-ink-faint mb-5 [&>svg]:w-6 [&>svg]:h-6">
        {icon}
      </div>
      <h3 className="font-serif font-normal text-xl text-ink">{title}</h3>
      {description && (
        <p className="mt-2 text-[13px] text-ink-faint max-w-sm font-body">{description}</p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}
