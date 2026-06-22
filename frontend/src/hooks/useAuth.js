import { useState, useCallback, useEffect } from 'react'
import { apiUrl } from '../api'
import { readAnonPrefs } from './useProfile'

const TOKEN_KEY = 'atlas_token'
const USER_KEY = 'atlas_user'
const PREFS_KEY = 'atlas_prefs'

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
    async (email, username, password) => {
      // Carry the anonymous intake prefs onto the new account so signup keeps what the user already
      // told us. Only clear them once the account exists; a failed register leaves them in place.
      const preferences = readAnonPrefs()
      const ok = await submit('register', { email, username, password, ...(preferences ? { preferences } : {}) })
      if (ok) localStorage.removeItem(PREFS_KEY)
      return ok
    },
    [submit],
  )

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setUser(null)
  }, [])

  // Authed request against /api/users that returns a {ok, error, data} result instead of throwing,
  // so the settings screens can show inline errors. A 401 means the session lapsed: signal it the
  // same way the rest of the app does.
  const authed = useCallback(async (path, { method = 'POST', body } = {}) => {
    const token = localStorage.getItem(TOKEN_KEY)
    try {
      const res = await fetch(apiUrl(`/api/users/${path}`), {
        method,
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      })
      if (res.status === 401) window.dispatchEvent(new Event('atlas-unauthorized'))
      if (res.status === 204) return { ok: true }
      const data = await res.json().catch(() => ({}))
      if (!res.ok) return { ok: false, error: data.detail || 'Something went wrong' }
      return { ok: true, data }
    } catch {
      return { ok: false, error: 'Network error. Please try again.' }
    }
  }, [])

  const updateProfile = useCallback(
    async (fields) => {
      const res = await authed('me', { method: 'PATCH', body: fields })
      if (res.ok && res.data) {
        localStorage.setItem(USER_KEY, JSON.stringify(res.data))
        setUser(res.data)
      }
      return res
    },
    [authed],
  )

  const changePassword = useCallback(
    (currentPassword, newPassword) =>
      authed('me/password', { body: { current_password: currentPassword, new_password: newPassword } }),
    [authed],
  )

  const deleteAccount = useCallback(
    async (password) => {
      const res = await authed('me', { method: 'DELETE', body: { password } })
      if (res.ok) logout()
      return res
    },
    [authed, logout],
  )

  const forgotPassword = useCallback((email) => authed('forgot-password', { body: { email } }), [authed])

  const resendVerification = useCallback(() => authed('resend-verification', { body: {} }), [authed])

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

  return {
    user,
    error,
    busy,
    login,
    register,
    logout,
    updateProfile,
    changePassword,
    deleteAccount,
    forgotPassword,
    resendVerification,
  }
}
