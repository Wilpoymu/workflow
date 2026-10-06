interface BadgeProps {
  variant?: "default" | "success" | "warning" | "error" | "info"
  children: string
}

const variants = {
  default: "border-border text-ink-dim",
  success: "border-ok/40 text-ok",
  warning: "border-accent/40 text-accent",
  error: "border-danger/40 text-danger",
  info: "border-tag-blue/40 text-tag-blue",
}

export default function Badge({ variant = "default", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[10px] font-mono uppercase tracking-[0.12em] ${variants[variant]}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {children}
    </span>
  )
}
