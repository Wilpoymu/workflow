interface BadgeProps {
  variant?: "default" | "success" | "warning" | "error" | "info"
  children: string
}

const variants = {
  default: "bg-gray-800 text-gray-300",
  success: "bg-emerald-500/15 text-emerald-400",
  warning: "bg-amber-500/15 text-amber-400",
  error: "bg-red-500/15 text-red-400",
  info: "bg-sky-500/15 text-sky-400",
}

export default function Badge({ variant = "default", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium font-sans ${variants[variant]}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${variants[variant].split(" ")[1]}`} />
      {children}
    </span>
  )
}
