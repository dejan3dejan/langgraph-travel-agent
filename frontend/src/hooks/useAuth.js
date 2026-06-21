import { useState, useCallback, useEffect } from 'react'
import { apiUrl } from '../api'

const TOKEN_KEY = 'atlas_token'
const USER_KEY = 'atlas_user'

// Minimal JWT auth against /api/users. The token lives in localStorage and useChat
// reads it from there to authorize requests, so we don't prop-drill it around.
export function useAuth() {
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = useCallback(async (path, body) => {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/users/${path}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, session_id: localStorage.getItem('atlas_session_id') || null }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Something went wrong')

      localStorage.setItem(TOKEN_KEY, data.access_token)
      localStorage.setItem(USER_KEY, JSON.stringify(data.user))
      setUser(data.user)
      return true
    } catch (e) {
      setError(e.message)
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  const login = useCallback((email, password) => submit('login', { email, password }), [submit])

  const register = useCallback(
    (email, username, password) => submit('register', { email, username, password }),
    [submit],
  )

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setUser(null)
  }, [])

  // Validate a stored token on load: a stale/expired token would otherwise leave the header
  // showing a signed-in user while requests silently fall back to anonymous.
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return
    let cancelled = false
    fetch(apiUrl('/api/users/me'), { headers: { Authorization: `Bearer ${token}` } })
      .then(async (res) => {
        if (cancelled) return
        if (res.ok) {
          const u = await res.json()
          localStorage.setItem(USER_KEY, JSON.stringify(u))
          setUser(u)
        } else {
          localStorage.removeItem(TOKEN_KEY)
          localStorage.removeItem(USER_KEY)
          setUser(null)
        }
      })
      .catch(() => {
        // network error: keep the cached user and revalidate next load
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Any request that returns 401 dispatches this; treat it as an expired session.
  useEffect(() => {
    window.addEventListener('atlas-unauthorized', logout)
    return () => window.removeEventListener('atlas-unauthorized', logout)
  }, [logout])

  return { user, error, busy, login, register, logout }
}
