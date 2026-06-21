import { useState, useCallback, useEffect } from 'react'

const PREFS_KEY = 'atlas_prefs'
const INTAKE_DONE_KEY = 'atlas_intake_done'

function authHeaders() {
  const token = localStorage.getItem('atlas_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// The anonymous user's intake prefs, kept in localStorage until they sign up (then useAuth migrates
// them onto the account). Exported so useChat can seed the first plan and useAuth can read them at
// registration without mounting the hook.
export function readAnonPrefs() {
  const raw = localStorage.getItem(PREFS_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

// Traveler profile state. For an anonymous user it manages the first-run intake (localStorage); for
// a signed-in user it loads and updates the saved profile from /api/users/preferences.
export function useProfile(user) {
  const [intakeDone, setIntakeDone] = useState(() => localStorage.getItem(INTAKE_DONE_KEY) === '1')
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState(null)

  const saveIntake = useCallback((prefs) => {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
    localStorage.setItem(INTAKE_DONE_KEY, '1')
    setIntakeDone(true)
  }, [])

  const skipIntake = useCallback(() => {
    localStorage.setItem(INTAKE_DONE_KEY, '1')
    setIntakeDone(true)
  }, [])

  // Load the saved profile once a user is present. Keyed on the id, not the object, so a re-render
  // that hands us a fresh user object does not refetch in a loop. Anonymous users have no profile.
  const userId = user?.id
  useEffect(() => {
    if (!userId) {
      setProfile(null)
      return
    }
    let cancelled = false
    fetch('/api/users/preferences', { headers: authHeaders() })
      .then(async (res) => {
        if (cancelled) return
        if (res.status === 401) window.dispatchEvent(new Event('atlas-unauthorized'))
        if (res.ok) setProfile(await res.json())
        else setError(`Could not load profile (${res.status})`)
      })
      .catch((e) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  const updateProfile = useCallback(async (partial) => {
    const res = await fetch('/api/users/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(partial),
    })
    if (!res.ok) {
      if (res.status === 401) window.dispatchEvent(new Event('atlas-unauthorized'))
      setError(`Could not save profile (${res.status})`)
      return false
    }
    setProfile(await res.json())
    return true
  }, [])

  return { intakeDone, saveIntake, skipIntake, profile, updateProfile, error }
}
