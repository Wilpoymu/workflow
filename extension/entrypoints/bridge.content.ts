/**
 * bridge.content.ts — ISOLATED-world WebSocket client for flow.google.com.
 *
 * Adapted from flowkit (MIT) — github.com/crisng95/flowkit @ af5e058
 * (WS <-> page message mapping pattern).
 *
 * Connects to the local Workflow backend WS, forwards batchexecute RPC commands
 * to flow-executor.content.ts (MAIN world) over window.postMessage, and returns
 * the raw results. Account identity is the Chrome profile: the background
 * service worker answers WF_GET_PROFILE_META with {id, label}, and the account
 * hash sent to the backend is djb2(profileId).
 */
export default defineContentScript({
  matches: ["https://flow.google.com/*"],
  world: "ISOLATED",
  main() {
    const BRIDGE_WS = "ws://127.0.0.1:8766"
    const FALLBACK_PROFILE_ID = "profile:unknown"

    let ws: WebSocket | null = null
    let accountHash: string | null = null
    let accountEmail: string | null = null

    // id -> expected reply shape, so out-of-order results stay correlated.
    const pending = new Map<string, "generate" | "rpc">()

    function djb2Hash(str: string): string {
      let h = 5381
      for (let i = 0; i < str.length; i++) {
        h = ((h << 5) + h + str.charCodeAt(i)) & 0xffffffff
      }
      let hex = (h >>> 0).toString(16)
      while (hex.length < 8) hex = "0" + hex
      return hex
    }

    function register() {
      if (ws?.readyState !== WebSocket.OPEN || !accountHash) return
      ws.send(
        JSON.stringify({
          type: "register",
          account: accountHash,
          email: accountEmail || undefined,
        })
      )
    }

    function resolveProfileMeta() {
      try {
        chrome.runtime.sendMessage({ type: "WF_GET_PROFILE_META" }, (resp) => {
          void chrome.runtime.lastError // suppress "no receiver" noise; fallback below
          const profileId = resp?.id || FALLBACK_PROFILE_ID
          accountHash = djb2Hash(profileId)
          accountEmail = resp?.label || null
          register()
        })
      } catch {
        accountHash = djb2Hash(FALLBACK_PROFILE_ID)
        accountEmail = null
        register()
      }
    }

    function connect() {
      ws = new WebSocket(BRIDGE_WS)

      ws.onopen = () => {
        console.log("[Workflow Bridge] WS connected")
        register()
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === "generate") {
            pending.set(msg.batchId, "generate")
            window.postMessage(
              { type: "WF_RPC_REQUEST", id: msg.batchId, requests: msg.requests },
              "*"
            )
          } else if (msg.type === "rpc") {
            pending.set(msg.id, "rpc")
            window.postMessage(
              {
                type: "WF_RPC_REQUEST",
                id: msg.id,
                requests: [
                  {
                    requestId: msg.rpcid,
                    rpcid: msg.rpcid,
                    freq: msg.freq,
                    captchaAction: msg.captchaAction ?? null,
                  },
                ],
              },
              "*"
            )
          }
        } catch {
          /* ignore malformed frames */
        }
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
      const data = event.data
      if (!data || data.type !== "WF_RPC_RESULT") return

      const kind = pending.get(data.id)
      if (!kind) return
      pending.delete(data.id)

      const results = Array.isArray(data.results) ? data.results : []
      if (ws?.readyState !== WebSocket.OPEN) return

      if (kind === "generate") {
        ws.send(JSON.stringify({ type: "result", batchId: data.id, results }))
      } else {
        const first = results[0] || { success: false, status: 0, data: "", error: "NO_RESULT" }
        ws.send(
          JSON.stringify({
            type: "rpc_result",
            id: data.id,
            success: !!first.success,
            status: first.status ?? 0,
            data: first.data ?? "",
            error: first.error || "",
          })
        )
      }
    })

    resolveProfileMeta()
    connect()
  },
})
