import { useState } from 'react'
import { apiUrl } from '../api'

// Standalone page opened from a ?reset=<token> link. Posts the token plus a new password, then
// sends the user back to the app to sign in. The token is single-use and expiring server-side.
export default function ResetPassword({ token }) {
  const [password, setPassword] = useState('')
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setStatus('working')
    setError(null)
    try {
      const res = await fetch(apiUrl('/api/users/reset-password'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Could not reset your password.')
      }
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('idle')
    }
  }

  return (
    <div className="modal-backdrop modal-backdrop--page">
      <div className="auth-card">
        <h2 className="auth-card__title">Reset password</h2>
        {status === 'done' ? (
          <>
            <p className="auth-note">Your password has been reset. You can sign in with it now.</p>
            <a className="auth-submit auth-submit--link" href="/">Back to Atlas</a>
          </>
        ) : (
          <form className="auth-form" onSubmit={submit}>
            <input
              className="auth-input"
              type="password"
              placeholder="New password (6+ characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
            />
            {error && <p className="auth-error">{error}</p>}
            <button className="auth-submit" type="submit" disabled={status === 'working'}>
              {status === 'working' ? 'Working...' : 'Set new password'}
            </button>
            <a className="auth-toggle" href="/">Back to Atlas</a>
          </form>
        )}
      </div>
    </div>
  )
}
