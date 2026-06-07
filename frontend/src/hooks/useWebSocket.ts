import { useEffect, useRef, useState } from "react"

type WSMessage = Record<string, unknown>

export function useWebSocket(url: string | null) {
  const [messages, setMessages] = useState<WSMessage[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const retries = useRef(0)

  useEffect(() => {
    if (!url) return

    let ws: WebSocket

    function connect() {
      if (!url) return
      ws = new WebSocket(url)
      wsRef.current = ws
      retries.current = 0

      ws.onopen = () => setConnected(true)

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          setMessages((prev) => [...prev, data])

          if (data.type === "complete" || data.type === "error") {
            ws.close()
          }
        } catch {
          // ignore non-JSON messages
        }
      }

      ws.onclose = () => {
        setConnected(false)
        if (retries.current < 5) {
          retries.current++
          setTimeout(connect, 2000 * retries.current)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      ws.close()
    }
  }, [url])

  return { messages, connected }
}
