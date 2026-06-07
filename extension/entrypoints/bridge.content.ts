export default defineContentScript({
  matches: ["https://labs.google/fx/tools/flow*"],
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

      if (event.data.type === "FLOW_AUTH_RESULT") {
        const { account, token, email } = event.data
        accountHash = account
        accountEmail = email || null

        fetch("http://127.0.0.1:8000/api/auth/auto", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ account, token, email }),
        }).catch(console.error)

        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "register",
            account: accountHash,
            email: email || undefined,
          }))
        }
      }
    })

    connect()
  },
})
