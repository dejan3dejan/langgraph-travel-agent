import { useCallback, useState } from 'react'
import { apiUrl } from '../api'

// Posts an optional star rating and/or note to the backend. Used for plan, A/B, and app feedback.
export function useFeedback() {
  const [status, setStatus] = useState('idle') // idle | sending | sent | error

  const submit = useCallback(async ({ kind, rating = null, message = null, sessionId = null, context = null }) => {
    setStatus('sending')
    const headers = { 'Content-Type': 'application/json' }
    const token = localStorage.getItem('atlas_token')
    if (token) headers.Authorization = `Bearer ${token}`
    try {
      const res = await fetch(apiUrl('/api/feedback'), {
        method: 'POST',
        headers,
        body: JSON.stringify({
          kind,
          rating: rating || null,
          message: message || null,
          session_id: sessionId || null,
          context: context || null,
        }),
      })
      if (!res.ok) {
        setStatus('error')
        return false
      }
      setStatus('sent')
      return true
    } catch {
      setStatus('error')
      return false
    }
  }, [])

  const reset = useCallback(() => setStatus('idle'), [])

  return { status, submit, reset }
}
