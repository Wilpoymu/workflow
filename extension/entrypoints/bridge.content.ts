export default defineContentScript({
  matches: ["https://labs.google/fx/*/tools/flow*", "https://labs.google/fx/tools/flow*"],
  world: "ISOLATED",
  main() {
    const BRIDGE_WS = "ws://127.0.0.1:8766"

    let ws: WebSocket | null = null
    let accountHash: string | null = null
    let accountEmail: string | null = null

    function connect() {
      ws = new WebSocket(BRIDGE_WS)

      ws.onopen = () => {
        console.log("[Workflow Bridge] WS connected")
        if (accountHash) {
          ws!.send(JSON.stringify({
            type: "register",
            account: accountHash,
            email: accountEmail || undefined,
          }))
        }
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === "generate") {
            window.postMessage(
              {
                type: "FLOW_GENERATE_REQUEST",
                requests: msg.requests,
                batchId: msg.batchId,
              },
              "*"
            )
          }
        } catch { /* ignore */ }
      }

      ws.onclose = () => {
        console.log("[Workflow Bridge] WS disconnected, reconnecting in 5s")
        ws = null
        setTimeout(connect, 5000)
      }

      ws.onerror = () => ws?.close()
    }

    window.addEventListener("message", (event) => {
      if (event.source !== window) return

      if (event.data.type === "FLOW_GENERATE_RESULT") {
        const { batchId, results } = event.data
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "result", batchId, results }))
        }
      }

      // The static token-gen.js sends FLOW_ACCOUNT_HASH (not FLOW_AUTH_RESULT).
      // token-gen handles /api/auth/auto directly; we just need the hash for WS registration.
      if (event.data.type === "FLOW_ACCOUNT_HASH") {
        const { hash, email } = event.data
        accountHash = hash
        accountEmail = email || null
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "register",
            account: accountHash,
            email: accountEmail || undefined,
          }))
        }
      }
    })

    connect()
  },
})
