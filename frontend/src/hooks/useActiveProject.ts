import { useState } from "react"

const STORAGE_KEY = "workflow-active-project"

export function useActiveProject() {
  const [activeProject, setActiveProjectState] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY)
  })

  const setActiveProject = (projectId: string | null) => {
    if (projectId) {
      localStorage.setItem(STORAGE_KEY, projectId)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    setActiveProjectState(projectId)
  }

  return { activeProject, setActiveProject }
}
