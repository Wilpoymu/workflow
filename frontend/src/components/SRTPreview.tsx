import Card from "./Card"

interface SrtBlock {
  index: number
  start: string
  end: string
  text: string
}

interface SRTPreviewProps {
  blocks: SrtBlock[]
}

export default function SRTPreview({ blocks }: SRTPreviewProps) {
  if (blocks.length === 0) return null

  return (
    <div className="space-y-2 animate-fade-in">
      {blocks.map((block) => (
        <Card key={block.index} className="flex items-start gap-4 py-3 px-4">
          <div className="flex flex-col items-center gap-1 min-w-[72px]">
            <span className="text-xs font-mono text-accent font-medium">
              {block.index}
            </span>
            <span className="text-[10px] font-mono text-gray-700 leading-tight text-center">
              {block.start}<br />{block.end}
            </span>
          </div>
          <p className="text-sm text-gray-300 font-body leading-relaxed flex-1">
            {block.text}
          </p>
        </Card>
      ))}
    </div>
  )
}
