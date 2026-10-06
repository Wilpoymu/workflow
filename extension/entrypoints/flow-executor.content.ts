/**
 * flow-executor.content.ts — run signed batchexecute RPCs inside the Flow page.
 *
 * Adapted from flowkit (MIT) — github.com/crisng95/flowkit @ af5e058
 * (injected.js, background.js runBatchRpc).
 *
 * Runs in the MAIN world on flow.google.com: only the page itself can mint a
 * fresh reCAPTCHA and sign a call with the session cookie plus the per-page `at`
 * token. The ISOLATED-world bridge (bridge.content.ts) forwards RPC requests
 * here over window.postMessage; this script mints the captcha (through the
 * pristine execute captured by hijack-bypass.content.ts), issues the POST, and
 * posts the raw batchexecute text back.
 */
const CAPTCHA_SLOT = "__CAPTCHA__"
const FALLBACK_SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"

export default defineContentScript({
  matches: ["https://flow.google.com/*"],
  world: "MAIN",
  main() {
    // ── Captcha minting (serialized: concurrent mints must not interleave) ──

    let captchaMintTail: Promise<unknown> = Promise.resolve()

    function resolveSitekey(): string {
      try {
        const clients = (window as any).___grecaptcha_cfg?.clients || {}
        for (const key of Object.keys(clients)) {
          const client = clients[key]
          if (client && client.sitekey) return client.sitekey
        }
      } catch {
        /* fall through to the constant */
      }
      return FALLBACK_SITE_KEY
    }

    function waitForPristine(timeout = 22000): Promise<void> {
      return new Promise((resolve, reject) => {
        const started = Date.now()
        const check = () => {
          if (typeof (window as any).__wf_hijack?.pristine === "function") return resolve()
          if (Date.now() - started > timeout) {
            return reject(new Error("pristine execute not captured"))
          }
          setTimeout(check, 200)
        }
        check()
      })
    }

    async function executePristine(action: string): Promise<string> {
      await waitForPristine()
      let lastErr: unknown = null
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const pristine = (window as any).__wf_hijack?.pristine
          if (typeof pristine !== "function") throw new Error("pristine execute unavailable")
          const token = await Promise.race([
            pristine(resolveSitekey(), { action }),
            new Promise((_, reject) =>
              setTimeout(() => reject(new Error("execute_hang")), 8000)
            ),
          ])
          if (token) return String(token)
          lastErr = new Error("empty_token")
        } catch (e) {
          lastErr = e
        }
        await new Promise((r) => setTimeout(r, 600))
      }
      throw lastErr instanceof Error ? lastErr : new Error(String(lastErr || "execute_failed"))
    }

    function mintCaptcha(action: string): Promise<string> {
      const previous = captchaMintTail.catch(() => undefined)
      let release!: () => void
      captchaMintTail = new Promise<void>((resolve) => {
        release = resolve
      })
      return previous.then(
        () => executePristine(action).finally(() => release())
      )
    }

    // ── One batchexecute RPC ────────────────────────────────────────────────

    type RpcRequest = {
      requestId?: string
      rpcid?: string
      freq?: string
      captchaAction?: string | null
    }

    type RpcResult = {
      requestId: string | undefined
      success: boolean
      status: number
      data: string
      error: string
    }

    function failure(requestId: string | undefined, error: string): RpcResult {
      return { requestId, success: false, status: 0, data: "", error }
    }

    async function runOne(req: RpcRequest): Promise<RpcResult> {
      let freq = String(req.freq || "")

      if (req.captchaAction) {
        let token: string
        try {
          token = await mintCaptcha(String(req.captchaAction))
        } catch (e) {
          const reason = e instanceof Error ? e.message : String(e)
          return failure(req.requestId, `CAPTCHA_FAILED: ${reason}`)
        }
        // A freq can carry the marker more than once — replace ALL of them.
        freq = freq.split(CAPTCHA_SLOT).join(token)
      } else if (freq.includes(CAPTCHA_SLOT)) {
        return failure(
          req.requestId,
          "CAPTCHA_REQUIRED: freq contains __CAPTCHA__ but no captchaAction was provided"
        )
      }

      const wiz = (globalThis as any).WIZ_global_data || {}
      const at = wiz.SNlM0e
      const sid = wiz.FdrFJe
      const bl = wiz.cfb2h
      if (!at) return failure(req.requestId, "NO_AT_TOKEN")

      try {
        const reqid = Math.floor(Math.random() * 900000) + 100000
        // source-path is required: GEM_PIX_2 rejects image generation without it.
        const sourcePath = location.pathname || "/"
        const hl = (document.documentElement.lang || navigator.language || "en").split("-")[0]
        const url =
          `/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=${encodeURIComponent(String(req.rpcid || ""))}` +
          `&source-path=${encodeURIComponent(sourcePath)}` +
          `&bl=${encodeURIComponent(bl || "")}&f.sid=${encodeURIComponent(sid || "")}` +
          `&hl=${encodeURIComponent(hl)}&_reqid=${reqid}&rt=c`
        const resp = await fetch(url, {
          method: "POST",
          credentials: "include",
          headers: {
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "x-same-domain": "1",
          },
          body: new URLSearchParams({ "f.req": freq, at }),
        })
        const text = await resp.text()
        return {
          requestId: req.requestId,
          success: resp.ok,
          status: resp.status,
          data: text,
          error: "",
        }
      } catch (e) {
        return failure(req.requestId, e instanceof Error ? e.message : String(e))
      }
    }

    // ── Relay from the ISOLATED world ───────────────────────────────────────

    window.addEventListener("message", (event) => {
      if (event.source !== window) return
      const data = event.data
      if (!data || data.type !== "WF_RPC_REQUEST") return
      const id = data.id
      const requests: RpcRequest[] = Array.isArray(data.requests) ? data.requests : []

      ;(async () => {
        const results: RpcResult[] = []
        // Sequential within one message: Flow rate-limits parallel submits.
        for (const req of requests) results.push(await runOne(req))
        window.postMessage({ type: "WF_RPC_RESULT", id, results }, "*")
      })().catch((e) => {
        const reason = e instanceof Error ? e.message : String(e)
        window.postMessage(
          {
            type: "WF_RPC_RESULT",
            id,
            results: requests.map((req) => failure(req.requestId, reason)),
          },
          "*"
        )
      })
    })
  },
})
