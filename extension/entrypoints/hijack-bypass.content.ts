/**
 * hijack-bypass.content.ts — capture the pristine reCAPTCHA execute in MAIN world.
 *
 * Adapted from flowkit (MIT) — github.com/crisng95/flowkit @ af5e058
 * (hijack_bypass.js).
 *
 * Flow's frontend patches grecaptcha.enterprise.execute with a wrapper that
 * forces action: "extension_hijack_detected"; tokens minted through that public
 * path are rejected as PUBLIC_ERROR_UNUSUAL_ACTIVITY. This script runs at
 * document_start in the MAIN world — before Flow's trap — and captures the
 * pristine execute function the moment reCAPTCHA assigns it, exposing it on
 * window.__wf_hijack for flow-executor.content.ts.
 */
export default defineContentScript({
  matches: ["https://flow.google.com/*"],
  world: "MAIN",
  runAt: "document_start",
  main() {
    let pristineExecute: ((...args: any[]) => any) | null = null
    let capturedTrapped = false
    let cleanedUp = false

    function savePristine(fn: unknown, enterprise: any, _source: string): boolean {
      if (pristineExecute || typeof fn !== "function") return false
      // The trap wrapper carries this marker in its source; never capture it.
      try {
        if (String(fn).includes("extension_hijack_detected")) {
          capturedTrapped = true
          return false
        }
      } catch {
        /* toString on native code may throw — treat as plausibly pristine */
      }
      pristineExecute = (fn as any).bind(enterprise)
      Promise.resolve().then(cleanAllTraps)
      return true
    }

    function cleanTrap(obj: any, prop: string) {
      try {
        const desc = Object.getOwnPropertyDescriptor(obj, prop)
        if (!desc || (!desc.get && !desc.set)) return // already clean
        Object.defineProperty(obj, prop, {
          value: desc.get ? desc.get() : undefined,
          writable: true,
          configurable: true,
          enumerable: true,
        })
      } catch {
        /* frozen or non-configurable — leave it */
      }
    }

    function cleanAllTraps() {
      if (cleanedUp) return
      cleanedUp = true
      try {
        const gc = (window as any).grecaptcha
        if (gc) {
          const enterprise = gc.enterprise
          if (enterprise) cleanTrap(enterprise, "execute")
          cleanTrap(gc, "enterprise")
        }
        cleanTrap(window, "grecaptcha")
      } catch {
        /* best-effort */
      }
    }

    function watchExecute(enterprise: any) {
      let val = enterprise.execute
      if (typeof val === "function" && savePristine(val, enterprise, "L3-immediate")) return
      try {
        Object.defineProperty(enterprise, "execute", {
          get() {
            return val
          },
          set(fn) {
            val = fn
            savePristine(fn, enterprise, "L3-setter")
          },
          configurable: true,
          enumerable: true,
        })
      } catch {
        /* non-configurable — fall through to the poll */
      }
    }

    function watchEnterprise(grecaptcha: any) {
      let val = grecaptcha.enterprise
      if (val && typeof val === "object") watchExecute(val)
      try {
        Object.defineProperty(grecaptcha, "enterprise", {
          get() {
            return val
          },
          set(obj) {
            val = obj
            if (obj && typeof obj === "object") watchExecute(obj)
          },
          configurable: true,
          enumerable: true,
        })
      } catch {
        /* non-configurable */
      }
    }

    function installCapture() {
      let val = (window as any).grecaptcha
      if (val && typeof val === "object") watchEnterprise(val)
      try {
        Object.defineProperty(window, "grecaptcha", {
          get() {
            return val
          },
          set(obj) {
            val = obj
            if (obj && typeof obj === "object") watchEnterprise(obj)
          },
          configurable: true,
          enumerable: true,
        })
      } catch {
        /* non-configurable */
      }

      // Fallback A: rapid poll, in case a trap layer got clobbered.
      const pollId = setInterval(() => {
        if (pristineExecute) {
          clearInterval(pollId)
          return
        }
        try {
          const gc = (window as any).grecaptcha
          const exec = gc?.enterprise?.execute
          if (typeof exec === "function") {
            savePristine(exec, gc.enterprise, "poll-2ms")
            if (pristineExecute) clearInterval(pollId)
          }
        } catch {
          /* ignore */
        }
      }, 2)
      setTimeout(() => clearInterval(pollId), 30000)

      // Fallback B: ready() callback race, registered before Angular's own.
      const readyPollId = setInterval(() => {
        if (pristineExecute) {
          clearInterval(readyPollId)
          return
        }
        try {
          const gc = (window as any).grecaptcha
          const ready = gc?.enterprise?.ready
          if (typeof ready === "function") {
            clearInterval(readyPollId)
            ready.call(gc.enterprise, () => {
              try {
                const exec = (window as any).grecaptcha?.enterprise?.execute
                if (typeof exec === "function") {
                  savePristine(exec, (window as any).grecaptcha.enterprise, "ready-race")
                }
              } catch {
                /* ignore */
              }
            })
          }
        } catch {
          /* ignore */
        }
      }, 5)
      setTimeout(() => clearInterval(readyPollId), 30000)
    }

    installCapture()

    try {
      Object.defineProperty(window, "__wf_hijack", {
        value: Object.freeze({
          get pristine() {
            return pristineExecute
          },
          get trapped() {
            return capturedTrapped
          },
        }),
        writable: false,
        configurable: false,
        enumerable: false,
      })
    } catch {
      ;(window as any).__wf_hijack = {
        get pristine() {
          return pristineExecute
        },
        get trapped() {
          return capturedTrapped
        },
      }
    }
  },
})
