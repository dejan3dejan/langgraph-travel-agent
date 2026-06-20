import { useState, useCallback } from 'react'

// Creates a public, read-only snapshot of an itinerary and copies its link to the clipboard.
// Only the rendered markdown and the map payload are sent; nothing user-identifying.
export function useShare() {
  const [status, setStatus] = useState('idle')

  const share = useCallback(async ({ itinerary_text, geo }) => {
    setStatus('sharing')
    try {
      const res = await fetch('/api/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ itinerary_text, geo }),
      })
      if (!res.ok) throw new Error(`Share failed (${res.status})`)

      const { id } = await res.json()
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

  return { share, status }
}
