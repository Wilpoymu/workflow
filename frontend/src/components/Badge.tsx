interface BadgeProps {
  variant?: "default" | "success" | "warning" | "error" | "info"
  children: string
}

const variants = {
  default: "bg-foreground/10 text-foreground-secondary dark:bg-gray-800 dark:text-gray-300",
  success: "bg-emerald-500/15 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400",
  warning: "bg-amber-500/15 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400",
  error: "bg-red-500/15 text-red-600 dark:bg-red-500/15 dark:text-red-400",
  info: "bg-sky-500/15 text-sky-600 dark:bg-sky-500/15 dark:text-sky-400",
}

const dotColors = {
  default: "bg-foreground-secondary dark:bg-gray-300",
  success: "bg-emerald-600 dark:bg-emerald-400",
  warning: "bg-amber-600 dark:bg-amber-400",
  error: "bg-red-600 dark:bg-red-400",
  info: "bg-sky-600 dark:bg-sky-400",
}

export default function Badge({ variant = "default", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium font-sans ${variants[variant]}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotColors[variant]}`} />
      {children}
    </span>
  )
}
