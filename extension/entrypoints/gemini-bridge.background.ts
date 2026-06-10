/**
 * Gemini Web Cookie Bridge — Background Service Worker
 *
 * Extracts __Secure-1PSID and __Secure-1PSIDTS cookies from gemini.google.com
 * and pushes them to the Workflow backend for use in prompt generation.
 *
 * Adapted from Gemini Batch Studio's background.js approach.
 */

import { defineBackground } from "wxt/utils/define-background"

export default defineBackground({
  main() {
    const BACKEND_BASE = "http://127.0.0.1:8000"
    const PUSH_ALARM_MIN = 0.5
    const DEBOUNCE_MS = 1500

    const GEMINI_COOKIE_NAMES = [
      "__Secure-1PSID",
      "__Secure-1PSIDTS",
      "__Secure-1PSIDCC",
      "__Secure-1PSIDRTS",
      "SNID",
      "ACCOUNT_CHOOSER",
    ]

    const FALLBACK_DOMAINS = ["gemini.google.com", ".google.com"]
    const PROFILE_ID_KEY = "gemini_profile_id"
    const PROFILE_LABEL_KEY = "gemini_profile_label"

    const geminiTabs: Record<number, { url: string; last_active_ts: number; cookieStoreId: string | null }> = {}
    let geminiEverHadTab = false
    let geminiDebounceTimer: ReturnType<typeof setTimeout> | null = null
    let lastPushFingerprint = ""
    let profileMetaPromise: Promise<{ profileId: string; profileLabel: string }> | null = null

    function log(...args: unknown[]) {
      console.log("[Gemini Bridge]", ...args)
    }

    function isGeminiUrl(url: string | undefined): boolean {
      return !!url && url.includes("gemini.google.com")
    }

    function storageGet(keys: string[]): Promise<Record<string, string | undefined>> {
      return new Promise((resolve) => {
        try {
          chrome.storage.local.get(keys, (result) => resolve(result || {}))
        } catch {
          resolve({})
        }
      })
    }

    function storageSet(data: Record<string, string>): Promise<void> {
      return new Promise((resolve) => {
        try {
          chrome.storage.local.set(data, () => resolve())
        } catch {
          resolve()
        }
      })
    }

    function randomId(len = 12): string {
      const chars = "abcdefghijklmnopqrstuvwxyz0123456789"
      let out = ""
      for (let i = 0; i < len; i++) out += chars[Math.floor(Math.random() * chars.length)]
      return out
    }

    async function ensureProfileMeta(): Promise<{ profileId: string; profileLabel: string }> {
      if (profileMetaPromise) return profileMetaPromise
      profileMetaPromise = (async () => {
        const data = await storageGet([PROFILE_ID_KEY, PROFILE_LABEL_KEY])
        let profileId = data[PROFILE_ID_KEY]
        let profileLabel = data[PROFILE_LABEL_KEY]
        if (!profileId) profileId = `gemini_${randomId(10)}`
        if (!profileLabel) profileLabel = `Gemini ${profileId.slice(-4)}`
        await storageSet({ [PROFILE_ID_KEY]: profileId, [PROFILE_LABEL_KEY]: profileLabel })
        return { profileId, profileLabel }
      })()
      return profileMetaPromise
    }

    function trackGeminiTab(tab: chrome.tabs.Tab) {
      if (!tab || !tab.id || !isGeminiUrl(tab.url)) return
      geminiTabs[tab.id] = {
        url: tab.url || "",
        last_active_ts: Date.now() / 1000,
        cookieStoreId: tab.cookieStoreId || null,
      }
      geminiEverHadTab = true
    }

    function untrackGeminiTab(tabId: number) {
      delete geminiTabs[tabId]
    }

    function hasActiveTab(): boolean {
      return Object.keys(geminiTabs).length > 0
    }

    function getTabCount(): number {
      return Object.keys(geminiTabs).length
    }

    function getLastActive(): number {
      let max = 0
      for (const id in geminiTabs) {
        if (geminiTabs[id].last_active_ts > max) max = geminiTabs[id].last_active_ts
      }
      return max || Date.now() / 1000
    }

    function pickCookieStoreId(): string | null {
      let bestId: string | null = null
      let bestTs = -1
      for (const id in geminiTabs) {
        const t = geminiTabs[id]
        if (t.last_active_ts > bestTs) {
          bestTs = t.last_active_ts
          bestId = t.cookieStoreId || null
        }
      }
      return bestId
    }

    function getCookie(url: string, name: string, storeId?: string): Promise<chrome.cookies.Cookie | null> {
      return new Promise((resolve) => {
        try {
          const query: chrome.cookies.Details = { url, name }
          if (storeId) query.storeId = storeId
          chrome.cookies.get(query, (cookie) => {
            if (chrome.runtime.lastError) { resolve(null); return }
            resolve(cookie || null)
          })
        } catch { resolve(null) }
      })
    }

    function getAllForDomain(domain: string, storeId?: string): Promise<chrome.cookies.Cookie[]> {
      return new Promise((resolve) => {
        try {
          const query: chrome.cookies.GetAllDetails = { domain }
          if (storeId) query.storeId = storeId
          chrome.cookies.getAll(query, (cookies) => {
            if (chrome.runtime.lastError) { resolve([]); return }
            resolve(cookies || [])
          })
        } catch { resolve([]) }
      })
    }

    async function collectGeminiCookies(storeId: string | null): Promise<chrome.cookies.Cookie[]> {
      const collected: chrome.cookies.Cookie[] = []
      const seen = new Set<string>()

      async function tryDirect(name: string) {
        for (const url of ["https://gemini.google.com/", "https://google.com/", "https://www.google.com/"]) {
          const c = await getCookie(url, name, storeId || undefined)
          if (c && c.value) {
            const key = `${c.name}|${c.domain}|${c.path}|${c.storeId || ""}`
            if (!seen.has(key)) { seen.add(key); collected.push(c) }
            return
          }
        }
      }

      for (const name of GEMINI_COOKIE_NAMES) await tryDirect(name)
      for (const domain of FALLBACK_DOMAINS) {
        const cookies = await getAllForDomain(domain, storeId || undefined)
        for (const c of cookies) {
          if (GEMINI_COOKIE_NAMES.includes(c.name)) {
            const key = `${c.name}|${c.domain}|${c.path}|${c.storeId || ""}`
            if (!seen.has(key)) { seen.add(key); collected.push(c) }
          }
        }
      }
      return collected
    }

    function serializeCookies(cookies: chrome.cookies.Cookie[]): string {
      const order = ["SNID", "ACCOUNT_CHOOSER", "__Secure-1PSID", "__Secure-1PSIDTS", "__Secure-1PSIDCC", "__Secure-1PSIDRTS"]
      const byName: Record<string, string> = {}
      for (const c of cookies) { if (c && c.name && c.value && !byName[c.name]) byName[c.name] = c.value }
      return order.filter((n) => byName[n]).map((n) => `${n}=${byName[n]}`).join("; ")
    }

    function buildFingerprint(serialized: string, storeId: string | null, tabCount: number, hasTab: boolean): string {
      return `${storeId || "no-store"}|${serialized.length}|${tabCount}|${hasTab ? 1 : 0}`
    }

    async function pushGeminiCookiesNow() {
      if (!geminiEverHadTab) {
        updateBadge("waiting")
        log("No Gemini tab tracked yet; skipping push")
        return
      }

      const { profileId, profileLabel } = await ensureProfileMeta()
      const storeId = pickCookieStoreId()
      const cookies = await collectGeminiCookies(storeId)

      const hasPsid = cookies.some((c) => c.name === "__Secure-1PSID" && c.value)

      if (!cookies.length) {
        updateBadge("no-cookies")
        log("No cookies collected")
        return
      }

      const serialized = serializeCookies(cookies)
      const hasTab = hasActiveTab()
      const tabCount = getTabCount()
      const fp = buildFingerprint(serialized, storeId, tabCount, hasTab)

      if (fp === lastPushFingerprint && !hasTab) {
        log("Skip push (duplicate)")
        return
      }

      try {
        const res = await fetch(`${BACKEND_BASE}/api/bridge/gemini/cookies`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            profile_id: profileId,
            profile_label: profileLabel,
            cookie_header: serialized,
            has_active_tab: hasTab,
            cookie_names: cookies.map((c) => c.name),
            fingerprint: fp,
          }),
        })
        const result = await res.json()
        if (result?.ok !== false) {
          lastPushFingerprint = fp
          updateBadge(hasPsid ? "ok" : "no-cookies", hasPsid ? 1 : 0)
        } else {
          updateBadge("error")
        }
      } catch {
        updateBadge("error")
      }
    }

    // ── Badge ──────────────────────────────────────────────

    function updateBadge(state: "ok" | "no-cookies" | "waiting" | "error", count: number = 0) {
      try {
        if (!chrome.action) return
        switch (state) {
          case "ok":
            chrome.action.setBadgeText({ text: String(Math.min(count, 99)) })
            chrome.action.setBadgeBackgroundColor({ color: "#22c55e" })  // green
            chrome.action.setTitle({ title: `Gemini Web Bridge: ${count} cuenta(s) conectada(s)` })
            break
          case "no-cookies":
            chrome.action.setBadgeText({ text: "0" })
            chrome.action.setBadgeBackgroundColor({ color: "#6b7280" })  // gray
            chrome.action.setTitle({ title: "Gemini Web Bridge: sin cookies - abre gemini.google.com" })
            break
          case "waiting":
            chrome.action.setBadgeText({ text: "..." })
            chrome.action.setBadgeBackgroundColor({ color: "#6b7280" })  // gray
            chrome.action.setTitle({ title: "Gemini Web Bridge: esperando..." })
            break
          case "error":
            chrome.action.setBadgeText({ text: "!" })
            chrome.action.setBadgeBackgroundColor({ color: "#ef4444" })  // red
            chrome.action.setTitle({ title: "Gemini Web Bridge: error de conexion" })
            break
        }
      } catch { /* badge API may not be available in all contexts */ }
    }

    function debouncedPush() {
      if (geminiDebounceTimer) clearTimeout(geminiDebounceTimer)
      geminiDebounceTimer = setTimeout(pushGeminiCookiesNow, DEBOUNCE_MS)
    }

    // ── Event listeners ────────────────────────────────────

    chrome.tabs.onActivated.addListener((info) => {
      chrome.tabs.get(info.tabId, (tab) => {
        if (!chrome.runtime.lastError && isGeminiUrl(tab?.url)) { trackGeminiTab(tab); debouncedPush() }
      })
    })

    chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
      if (change.status === "complete" || change.url) {
        if (isGeminiUrl(tab?.url)) { trackGeminiTab(tab); debouncedPush() }
        else if (geminiTabs[tabId]) untrackGeminiTab(tabId)
      }
    })

    chrome.tabs.onRemoved.addListener((tabId) => { if (geminiTabs[tabId]) untrackGeminiTab(tabId) })

    // cookies.onChanged — wrap in try/catch for environments where it's mocked
    try { if (chrome.cookies?.onChanged) {
      chrome.cookies.onChanged.addListener((changeInfo) => {
        const c = changeInfo?.cookie
        if (c?.domain && c?.name && c.domain.includes("google.com") && GEMINI_COOKIE_NAMES.includes(c.name)) debouncedPush()
      })
    }} catch {}

    // Periodic alarm
    try { if (chrome.alarms) {
      chrome.alarms.create("gemini-cookie-push", { periodInMinutes: PUSH_ALARM_MIN })
      chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === "gemini-cookie-push") pushGeminiCookiesNow() })
    }} catch {}

    // Initial scans
    const scanTabs = () => {
      chrome.tabs.query({}, (tabs) => { for (const tab of tabs) trackGeminiTab(tab); pushGeminiCookiesNow() })
    }
    chrome.runtime.onInstalled.addListener(scanTabs)
    try { chrome.runtime.onStartup.addListener(scanTabs) } catch {}
    // Also run immediately since service worker may start fresh
    scanTabs()

    log("Service worker started")
  },
})
