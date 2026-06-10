import { defineConfig } from "wxt"

export default defineConfig({
  manifest: {
    name: "Workflow Bridge",
    version: "1.1.0",
    description: "Bridge between Workflow and Google services (Flow + Gemini Web)",
    permissions: [
      "storage",
      "cookies",
      "tabs",
      "alarms",
    ],
    host_permissions: [
      "https://labs.google/*",
      "https://aisandbox-pa.googleapis.com/*",
      "https://gemini.google.com/*",
      "https://google.com/*",
      "https://www.google.com/*",
      "http://127.0.0.1:*/*",
    ],
    background: {
      service_worker: "gemini-bridge.js",
      type: "module",
    },
  },
})
