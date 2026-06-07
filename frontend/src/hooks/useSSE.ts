import { useEffect, useRef, useState } from "react"

interface SSEEvent {
  type: string
  data: Record<string, unknown>
}

export function useSSE(url: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([])
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!url) return

    const es = new EventSource(url)
    esRef.current = es
    setConnected(true)

    es.addEventListener("progress", (e) => {
      setEvents((prev) => [
        ...prev,
        { type: "progress", data: JSON.parse(e.data) },
      ])
    })

    es.addEventListener("item_result", (e) => {
      setEvents((prev) => [
        ...prev,
        { type: "item_result", data: JSON.parse(e.data) },
      ])
    })

    es.addEventListener("complete", (e) => {
      setEvents((prev) => [
        ...prev,
        { type: "complete", data: JSON.parse(e.data) },
      ])
      es.close()
      setConnected(false)
    })

    es.addEventListener("error", () => {
      setConnected(false)
    })

    es.onerror = () => {
      setConnected(false)
    }

    return () => {
      es.close()
      setConnected(false)
    }
  }, [url])

  return { events, connected }
}
