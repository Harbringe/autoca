// Where this code is running, and where the server is.
//
// This folder is the only place the application knows whether it is a web page
// or a desktop shell. Everything else asks these modules for what it needs, so
// moving to Tauri means changing the files here and nothing under src/features.

/** Empty on the web, where the host proxies /api and /auth so the app is one origin. */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export const isTauri: boolean = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

/** Absolute URL for a server path such as "/admin/". */
export function serverUrl(path: string): string {
  return `${API_BASE}${path}`
}
