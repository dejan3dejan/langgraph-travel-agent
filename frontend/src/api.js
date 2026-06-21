// Base URL for the backend. Empty in dev so the Vite proxy serves /api and /health; set
// VITE_API_URL to the backend origin in production, where there is no proxy in front of the
// static build.
const API_BASE = import.meta.env.VITE_API_URL ?? ''

export function buildApiUrl(base, path) {
  return `${(base || '').replace(/\/$/, '')}${path}`
}

export function apiUrl(path) {
  return buildApiUrl(API_BASE, path)
}
