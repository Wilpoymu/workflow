import { useEffect, useRef, useState, useCallback, useMemo } from "react"
import {
  X,
  Scissors,
  Clock,
  Loader2,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
} from "lucide-react"
import { api } from "../api/client"

interface Word {
  text: string
  start: number
  end: number
  type: string
}

interface SelectionRange {
  startIdx: number
  endIdx: number
}

interface Paragraph {
  startIdx: number
  endIdx: number
}

interface ScriptSelectorProps {
  projectId: string
  onSelect: (startSec: number, endSec: number, text: string, startWordIdx: number, endWordIdx: number) => void
  onClose: () => void
}

const GAP_THRESHOLD = 0.7 // seconds gap = paragraph break

function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${m}:${s.toString().padStart(2, "0")}.${cs.toString().padStart(2, "0")}`
}

function fmtDuration(sec: number): string {
  if (sec >= 60) {
    const m = Math.floor(sec / 60)
    const s = Math.round(sec % 60)
    return `${m}m ${s}s`
  }
  return `${Math.round(sec)}s`
}

function buildParagraphs(words: Word[]): Paragraph[] {
  const paragraphs: Paragraph[] = []
  let paraStart = 0
  for (let i = 1; i < words.length; i++) {
    const gap = words[i].start - words[i - 1].end
    if (gap > GAP_THRESHOLD) {
      paragraphs.push({ startIdx: paraStart, endIdx: i - 1 })
      paraStart = i
    }
  }
  paragraphs.push({ startIdx: paraStart, endIdx: words.length - 1 })
  return paragraphs
}

export default function ScriptSelector({ projectId, onSelect, onClose }: ScriptSelectorProps) {
  const [words, setWords] = useState<Word[]>([])
  const [scriptText, setScriptText] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<SelectionRange | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState<number | null>(null)
  const [hoveredWord, setHoveredWord] = useState<number | null>(null)
  const [maxDuration] = useState(90)
  const containerRef = useRef<HTMLDivElement>(null)

  // Build paragraphs from text.txt structure (split by \n\n), fall back to time-gap heuristic
  const paragraphs = useMemo(() => {
    if (!scriptText) return buildParagraphs(words)
    const paraTexts = scriptText.split(/\n\n+/).filter((p) => p.trim())
    const result: Paragraph[] = []
    let wordIdx = 0
    for (const para of paraTexts) {
      const paraWordCount = para.split(/\s+/).filter((w) => w.trim()).length
      if (paraWordCount === 0) continue
      const startIdx = wordIdx
      wordIdx += paraWordCount
      const endIdx = Math.min(wordIdx - 1, words.length - 1)
      if (startIdx <= endIdx && startIdx < words.length) {
        result.push({ startIdx, endIdx })
      }
    }
    // Fallback: if result doesn't cover all words, use time-gap method
    if (result.length === 0 || result[result.length - 1].endIdx < words.length - 10) {
      return buildParagraphs(words)
    }
    return result
  }, [scriptText, words])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.getWordTimestamps(projectId),
      api.getScript(projectId).catch(() => null),
    ])
      .then(([wordRes, scriptRes]) => {
        setWords(wordRes.words.filter((w) => w.type === "word"))
        if (scriptRes?.text) setScriptText(scriptRes.text)
      })
      .catch((err) => setError(err?.message ?? "Failed to load word timestamps"))
      .finally(() => setLoading(false))
  }, [projectId])

  const handleWordMouseDown = useCallback((idx: number) => {
    setIsDragging(true)
    setDragStart(idx)
    setSelection({ startIdx: idx, endIdx: idx })
  }, [])

  const handleWordMouseEnter = useCallback((idx: number) => {
    setHoveredWord(idx)
    if (isDragging && dragStart !== null) {
      setSelection({
        startIdx: Math.min(dragStart, idx),
        endIdx: Math.max(dragStart, idx),
      })
    }
  }, [isDragging, dragStart])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
    setDragStart(null)
  }, [])

  useEffect(() => {
    window.addEventListener("mouseup", handleMouseUp)
    return () => window.removeEventListener("mouseup", handleMouseUp)
  }, [handleMouseUp])

  const selectedWords = selection ? words.slice(selection.startIdx, selection.endIdx + 1) : []
  const startSec = selectedWords.length > 0 ? selectedWords[0].start : 0
  const endSec = selectedWords.length > 0 ? selectedWords[selectedWords.length - 1].end : 0
  const duration = endSec - startSec
  const overMax = duration > maxDuration

  const handleConfirm = () => {
    if (!selection || selectedWords.length === 0) return
    const text = selectedWords.map((w) => w.text).join(" ")
    onSelect(startSec, endSec, text, selection.startIdx, selection.endIdx)
    onClose()
  }

  const adjustSelection = (delta: number) => {
    if (!selection) return
    const totalWords = words.length
    const newStart = Math.max(0, Math.min(selection.startIdx + delta, selection.endIdx - 1))
    const newEnd = Math.max(newStart + 1, Math.min(selection.endIdx + delta, totalWords - 1))
    if (newStart < newEnd) {
      setSelection({ startIdx: newStart, endIdx: newEnd })
    }
  }

  // Find which paragraph a word index belongs to
  const wordToParagraph = useMemo(() => {
    const map = new Map<number, number>()
    paragraphs.forEach((p, pi) => {
      for (let i = p.startIdx; i <= p.endIdx; i++) {
        map.set(i, pi)
      }
    })
    return map
  }, [paragraphs])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface-card shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-surface-hover text-gray-500 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
          <div>
            <h2 className="text-sm font-semibold text-white font-sans">Script Editor</h2>
            <p className="text-[11px] text-gray-600 font-mono">
              {loading ? "Loading..." : `${words.length} words · ${paragraphs.length} paragraphs${scriptText ? " (from text)" : ""}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-600 font-mono px-2 py-1 bg-surface-hover rounded">
            Max {maxDuration}s
          </span>
        </div>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-8 h-8 text-accent animate-spin" />
            <p className="text-sm text-gray-500 font-mono">Loading word timestamps...</p>
          </div>
        </div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3 text-center max-w-md">
            <AlertCircle className="w-10 h-10 text-red-400/60" />
            <p className="text-sm text-red-400">{error}</p>
            <button className="btn-secondary text-xs" onClick={onClose}>Close</button>
          </div>
        </div>
      ) : (
        <>
          {/* Selection info bar — fixed height to prevent DOM shifting */}
          {selection && (
            <div className="h-[185px] shrink-0 bg-surface-card border-b border-border overflow-y-auto">
              <div className="px-6 py-3">
                <div className="flex items-center gap-4 text-xs">
                  <div className="flex items-center gap-1.5 text-gray-400">
                    <Clock className="w-3 h-3" />
                    <span className="font-mono">{fmtTime(startSec)}</span>
                    <span className="text-gray-600">→</span>
                    <span className="font-mono">{fmtTime(endSec)}</span>
                  </div>
                  <div className="h-4 w-px bg-border" />
                  <span className={`font-mono font-semibold ${overMax ? "text-red-400" : "text-accent"}`}>
                    {fmtDuration(duration)}
                  </span>
                  <div className="h-4 w-px bg-border" />
                  <span className="text-gray-500 font-mono">{selectedWords.length} words</span>
                  {overMax && (
                    <>
                      <div className="h-4 w-px bg-border" />
                      <span className="text-red-400/80 text-[11px] flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" /> Exceeds {maxDuration}s
                      </span>
                    </>
                  )}
                </div>
                <div className="mt-2 h-1.5 bg-surface-hover rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-150 ${overMax ? "bg-red-500" : "bg-accent"}`}
                    style={{ width: `${Math.min(100, (duration / maxDuration) * 100)}%` }}
                  />
                </div>

                {/* Selected text preview — fixed internal height */}
                <div className="mt-3 p-3 bg-surface-hover rounded-lg border border-border/50">
                  <p className="text-xs text-gray-500 font-sans font-semibold mb-1.5 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400/60" />
                    Selected Text
                    <span className="text-gray-700 font-mono text-[10px] ml-auto">
                      {selectedWords.length} words · {selectedWords.join(" ").length} chars
                    </span>
                  </p>
                  <div className="max-h-[60px] overflow-y-auto">
                    <p className="text-sm text-gray-300 leading-relaxed font-sans">
                      {selectedWords.map((w) => w.text).join(" ")}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Script text area — paragraphs */}
          <div
            ref={containerRef}
            className="flex-1 overflow-y-auto px-6 py-8 select-none"
            onMouseUp={handleMouseUp}
            onMouseLeave={() => !isDragging && setHoveredWord(null)}
          >
            <div className="max-w-3xl mx-auto space-y-8">
              {paragraphs.map((para, pi) => {
                const paraWords = words.slice(para.startIdx, para.endIdx + 1)
                const paraDuration = paraWords[paraWords.length - 1].end - paraWords[0].start
                return (
                  <div key={pi} className="relative">
                    {/* Paragraph number gutter */}
                    <div className="absolute -left-12 top-0 flex flex-col items-center gap-1">
                      <span className="text-[10px] font-mono text-gray-700 font-semibold leading-none">
                        {String(pi + 1).padStart(2, "0")}
                      </span>
                      {paraDuration > 2 && (
                        <span className="text-[9px] font-mono text-gray-700 leading-none">
                          {fmtDuration(paraDuration)}
                        </span>
                      )}
                    </div>

                    {/* Divider line before paragraph (except first) */}
                    {pi > 0 && (
                      <div className="absolute -top-4 left-0 right-0 flex items-center gap-3">
                        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-border to-transparent" />
                      </div>
                    )}

                    {/* Words */}
                    <div className="font-mono text-[15px] leading-[2] text-gray-300">
                      {paraWords.map((word, wi) => {
                        const idx = para.startIdx + wi
                        const isSelected = selection && idx >= selection.startIdx && idx <= selection.endIdx
                        const isHovered = hoveredWord === idx
                        return (
                          <span
                            key={idx}
                            data-word-idx={idx}
                            onMouseDown={() => handleWordMouseDown(idx)}
                            onMouseEnter={() => handleWordMouseEnter(idx)}
                            className={`
                              inline cursor-pointer rounded-sm px-[1px] py-[1px] mx-[0.5px]
                              transition-colors duration-75
                              ${isSelected
                                ? "bg-amber-400/30 text-white shadow-[0_0_0_1px_rgba(251,191,36,0.3)]"
                                : isHovered && !isDragging
                                  ? "bg-white/5"
                                  : "hover:bg-white/5"
                              }
                            `}
                          >
                            {word.text}{" "}
                          </span>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Bottom action bar */}
          <div className="shrink-0 border-t border-border bg-surface-card px-6 py-4">
            <div className="flex items-center justify-between max-w-3xl mx-auto">
              <div className="flex items-center gap-2">
                <button
                  className="p-2 rounded-lg hover:bg-surface-hover text-gray-500 hover:text-white transition-colors disabled:opacity-30"
                  disabled={!selection}
                  onClick={() => adjustSelection(-5)}
                  title="Expand start (5 words earlier)"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                {selection && (
                  <span className="text-[10px] text-gray-600 font-mono px-2 py-1 bg-surface-hover rounded">
                    Para {wordToParagraph.get(selection.startIdx)! + 1}
                    {wordToParagraph.get(selection.startIdx) !== wordToParagraph.get(selection.endIdx)
                      ? `–${wordToParagraph.get(selection.endIdx)! + 1}`
                      : ""}
                  </span>
                )}
                <button
                  className="p-2 rounded-lg hover:bg-surface-hover text-gray-500 hover:text-white transition-colors disabled:opacity-30"
                  disabled={!selection}
                  onClick={() => adjustSelection(5)}
                  title="Expand end (5 words later)"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>

              <div className="flex items-center gap-3">
                {selection && overMax && (
                  <span className="text-[11px] text-red-400/80">Try a shorter selection</span>
                )}
                <button className="btn-secondary text-xs" onClick={onClose}>Cancel</button>
                <button
                  className={`btn-primary text-xs ${overMax ? "opacity-50" : ""}`}
                  disabled={!selection || selectedWords.length === 0 || overMax}
                  onClick={handleConfirm}
                >
                  <Scissors className="w-3.5 h-3.5" />
                  Add to Shorts
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
