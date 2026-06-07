import type { ReactNode, HTMLAttributes } from "react"

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  hover?: boolean
  children: ReactNode
}

export default function Card({ hover, children, className = "", ...props }: CardProps) {
  return (
    <div
      className={`${hover ? "card-hover" : "card"} ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}
