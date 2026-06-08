import { useState, useCallback } from 'react'

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
      const res = await fetch(`/api/users/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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

  return { user, error, busy, login, register, logout }
}
