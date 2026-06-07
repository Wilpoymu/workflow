export default defineContentScript({
  matches: ["https://labs.google/fx/tools/flow*"],
  world: "MAIN",
  main() {
    const SITE_KEY = "6LfHnb0pAAAAAH-nUzkjRxhFkBWUE0tY2sYA_6Vf"
    const TOKEN_POOL_SIZE = 5
    const TOKEN_REFRESH_INTERVAL = 100_000

    let tokenPool: string[] = []
    let sessionToken: string | null = null

    async function getRecaptchaToken(): Promise<string> {
      return (window as any).grecaptcha.enterprise.execute(SITE_KEY, { action: "IMAGE_GENERATION" })
    }

    async function refreshTokenPool() {
      const promises = Array.from({ length: TOKEN_POOL_SIZE }, () =>
        getRecaptchaToken().catch(() => null)
      )
      const tokens = (await Promise.all(promises)).filter(Boolean) as string[]
      if (tokens.length) tokenPool = tokens
    }

    function getToken(): string | null {
      return tokenPool.shift() ?? null
    }

    async function autoAuth() {
      for (let attempt = 0; attempt < 5; attempt++) {
        try {
          const res = await fetch("/fx/api/auth/session")
          const data = await res.json()
          if (data.access_token) {
            sessionToken = data.access_token
            const email = data.user?.email ?? "unknown"
            const hash = btoa(email).replace(/=/g, "")
            window.postMessage(
              { type: "FLOW_AUTH_RESULT", account: hash, token: sessionToken, email: email },
              "*"
            )
            return
          }
        } catch { /* retry */ }
        await new Promise((r) => setTimeout(r, 3000))
      }
    }

    async function handleGenerateRequest(requests: any[], batchId: string) {
      const results: any[] = []
      for (const req of requests) {
        try {
          const token = getToken()
          if (token && req.body) req.body.recaptchaToken = token

          const res = await fetch(
            "https://labs.google/fx/tools/flow/aisandbox-pa/api/generate",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${sessionToken}`,
              },
              body: JSON.stringify(req.body),
            }
          )
          const data = await res.json()
          results.push({ requestId: req.requestId, success: true, data })
        } catch (err) {
          results.push({ requestId: req.requestId, success: false, error: String(err) })
        }
      }
      window.postMessage(
        { type: "FLOW_GENERATE_RESULT", batchId, results },
        "*"
      )
    }

    window.addEventListener("message", async (event) => {
      if (event.source !== window) return
      if (event.data.type === "FLOW_GENERATE_REQUEST") {
        await handleGenerateRequest(event.data.requests, event.data.batchId)
      }
    })

    autoAuth()
    refreshTokenPool()
    setInterval(refreshTokenPool, TOKEN_REFRESH_INTERVAL)
    setInterval(autoAuth, 60_000)
  },
})
