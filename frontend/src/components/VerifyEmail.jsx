import { useEffect, useState } from 'react'
import { apiUrl } from '../api'

// Standalone page opened from a ?verify=<token> link. Confirms the email on mount, then offers a
// way back into the app. The token is single-use and expiring server-side.
export default function VerifyEmail({ token }) {
  const [status, setStatus] = useState('verifying')

  useEffect(() => {
    let active = true
    fetch(apiUrl('/api/users/verify-email'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then((res) => active && setStatus(res.ok ? 'verified' : 'failed'))
      .catch(() => active && setStatus('failed'))
    return () => {
      active = false
    }
  }, [token])

  const copy = {
    verifying: 'Verifying your email...',
    verified: 'Your email is verified. Thanks for confirming.',
    failed: 'This verification link is invalid or has expired. Sign in and request a new one.',
  }

  return (
    <div className="modal-backdrop modal-backdrop--page">
      <div className="auth-card">
        <h2 className="auth-card__title">Email verification</h2>
        <p className="auth-note">{copy[status]}</p>
        {status !== 'verifying' && <a className="auth-submit auth-submit--link" href="/">Back to Atlas</a>}
      </div>
    </div>
  )
}
