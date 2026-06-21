import { useState, useCallback } from 'react'
import { apiUrl } from '../api'

const LAST_SHARE_KEY = 'atlas_last_share'

function loadLastShare() {
  try {
    return JSON.parse(localStorage.getItem(LAST_SHARE_KEY)) || null
  } catch {
    return null
  }
}

// Creates a public, read-only snapshot of an itinerary and copies its link to the clipboard.
// Only the rendered markdown and the map payload are sent; nothing user-identifying. The revoke
// token returned at creation is kept (and persisted) so the same session can later unshare.
export function useShare() {
  const [status, setStatus] = useState('idle')
  const [lastShare, setLastShare] = useState(loadLastShare)

  const share = useCallback(async ({ itinerary_text, geo }) => {
    setStatus('sharing')
    try {
      const res = await fetch(apiUrl('/api/share'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ itinerary_text, geo }),
      })
      if (!res.ok) throw new Error(`Share failed (${res.status})`)

      const { id, revoke_token } = await res.json()
      const record = { id, revoke_token }
      setLastShare(record)
      localStorage.setItem(LAST_SHARE_KEY, JSON.stringify(record))

      const url = `${window.location.origin}/?share=${id}`
      await navigator.clipboard.writeText(url)
      setStatus('copied')
      setTimeout(() => setStatus('idle'), 2000)
      return url
    } catch {
      setStatus('error')
      setTimeout(() => setStatus('idle'), 2000)
      return null
    }
  }, [])

  const unshare = useCallback(async () => {
    if (!lastShare?.id) return false
    try {
      const res = await fetch(apiUrl(`/api/share/${lastShare.id}`), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revoke_token: lastShare.revoke_token }),
      })
      // 404 means it is already gone, which is the outcome we wanted either way.
      if (!res.ok && res.status !== 404) throw new Error(`Unshare failed (${res.status})`)
      setLastShare(null)
      localStorage.removeItem(LAST_SHARE_KEY)
      setStatus('idle')
      return true
    } catch {
      setStatus('error')
      setTimeout(() => setStatus('idle'), 2000)
      return false
    }
  }, [lastShare])

  return { share, unshare, status, isShared: !!lastShare, lastShare }
}
