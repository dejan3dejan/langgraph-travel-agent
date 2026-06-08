import { useState, useCallback, useEffect } from 'react'

function authHeaders() {
  const token = localStorage.getItem('atlas_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Loads the logged-in user's saved trips from /api/users/trips. Degrades to an explicit
// error message rather than silently showing an empty list.
export function useTrips(user) {
  const [trips, setTrips] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    if (!user) {
      setTrips([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/users/trips', { headers: authHeaders() })
      if (!res.ok) throw new Error(`Could not load trips (${res.status})`)
      setTrips(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    refresh()
  }, [refresh])

  const remove = useCallback(async (id) => {
    const res = await fetch(`/api/users/trips/${id}`, { method: 'DELETE', headers: authHeaders() })
    if (res.ok) setTrips((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const getDetail = useCallback(async (id) => {
    const res = await fetch(`/api/users/trips/${id}`, { headers: authHeaders() })
    return res.ok ? res.json() : null
  }, [])

  return { trips, loading, error, refresh, remove, getDetail }
}
