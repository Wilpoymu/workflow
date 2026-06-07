import { defineConfig } from "wxt"

export default defineConfig({
  manifest: {
    name: "Workflow Bridge",
    version: "1.0.0",
    description: "Bridge between Workflow and Google Flow for image generation",
    permissions: ["storage"],
    host_permissions: ["https://labs.google/*"],
  },
})
