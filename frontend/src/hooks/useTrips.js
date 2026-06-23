import { useState, useCallback, useEffect } from 'react'
import { apiUrl } from '../api'

function authHeaders() {
  const token = localStorage.getItem('atlas_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Loads the logged-in user's saved trips from /api/users/trips, plus trips shared with them by
// other users. Degrades to an explicit error message rather than silently showing an empty list.
export function useTrips(user) {
  const [trips, setTrips] = useState([])
  const [sharedTrips, setSharedTrips] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    if (!user) {
      setTrips([])
      setSharedTrips([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [ownedRes, sharedRes] = await Promise.all([
        fetch(apiUrl('/api/users/trips'), { headers: authHeaders() }),
        fetch(apiUrl('/api/users/trips/shared'), { headers: authHeaders() }),
      ])
      if (!ownedRes.ok) {
        if (ownedRes.status === 401) window.dispatchEvent(new Event('atlas-unauthorized'))
        throw new Error(`Could not load trips (${ownedRes.status})`)
      }
      setTrips(await ownedRes.json())
      setSharedTrips(sharedRes.ok ? await sharedRes.json() : [])
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
    const res = await fetch(apiUrl(`/api/users/trips/${id}`), { method: 'DELETE', headers: authHeaders() })
    if (res.ok) setTrips((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const getDetail = useCallback(async (id) => {
    const res = await fetch(apiUrl(`/api/users/trips/${id}`), { headers: authHeaders() })
    return res.ok ? res.json() : null
  }, [])

  const getSession = useCallback(async (sessionId) => {
    const res = await fetch(apiUrl(`/api/users/sessions/${sessionId}`), { headers: authHeaders() })
    return res.ok ? res.json() : null
  }, [])

  // Fire-and-forget: record that the user reopened a saved trip, an implicit signal that they value
  // it. Never blocks or surfaces an error; personalization is best-effort.
  const reportOpen = useCallback(async (tripId) => {
    try {
      await fetch(apiUrl('/api/signals'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ event_type: 'trip_opened', trip_id: tripId }),
      })
    } catch {
      // ignore: a missed signal must never affect the user's flow
    }
  }, [])

  // Invite a registered user to one of the owner's trips. Returns null on success, an error message
  // on failure, so the caller can surface a precise reason (unknown email, not the owner).
  const invite = useCallback(async (tripId, email, role) => {
    const res = await fetch(apiUrl(`/api/users/trips/${tripId}/members`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ email, role }),
    })
    if (res.ok) return null
    const data = await res.json().catch(() => ({}))
    return data.detail || `Could not invite (${res.status})`
  }, [])

  return { trips, sharedTrips, loading, error, refresh, remove, getDetail, getSession, reportOpen, invite }
}
