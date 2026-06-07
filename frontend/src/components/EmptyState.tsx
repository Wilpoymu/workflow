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
      <div className="text-gray-600 mb-4 [&>svg]:w-12 [&>svg]:h-12">
        {icon}
      </div>
      <h3 className="text-lg font-semibold text-gray-300">{title}</h3>
      {description && (
        <p className="mt-1 text-sm text-gray-600 max-w-sm">{description}</p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}
