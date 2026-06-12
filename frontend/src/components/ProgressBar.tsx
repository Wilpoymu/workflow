interface ProgressBarProps {
  progress: number
  label?: string
  subtitle?: string
  chips?: { label: string; value: string; color?: string }[]
}

export default function ProgressBar({ progress, label, subtitle, chips }: ProgressBarProps) {
  const pct = Math.min(Math.max(progress, 0), 100)

  return (
    <div className="w-full space-y-2">
      {label && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-300 font-body truncate">{label}</span>
          <span className="text-xs font-mono text-accent font-medium shrink-0 ml-2">{Math.round(pct)}%</span>
        </div>
      )}
      <div className="h-2 bg-surface-hover rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300 ease-out"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, #2dd4bf, #38bdf8)",
          }}
        />
      </div>
      {subtitle && (
        <p className="text-xs text-gray-500 font-body">{subtitle}</p>
      )}
      {chips && chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {chips.map((chip, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-surface-hover"
            >
              <span className="text-gray-500">{chip.label}:</span>
              <span className={chip.color ?? "text-gray-300"}>{chip.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
