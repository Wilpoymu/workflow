interface ProgressBarProps {
  progress: number
  label?: string
}

export default function ProgressBar({ progress, label }: ProgressBarProps) {
  const pct = Math.min(Math.max(progress, 0), 100)

  return (
    <div className="w-full">
      {label && (
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-sm text-gray-500 font-body">{label}</span>
          <span className="text-xs font-mono text-accent font-medium">{Math.round(pct)}%</span>
        </div>
      )}
      <div className="h-2 bg-surface-hover rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, #2dd4bf, #38bdf8)",
          }}
        />
      </div>
    </div>
  )
}
