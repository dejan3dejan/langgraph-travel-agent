import { useState } from 'react'

export default function AuthModal({ auth, onClose }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (mode === 'forgot') {
      setBusy(true)
      setNotice(null)
      const res = await auth.forgotPassword(email)
      setBusy(false)
      // Always confirm the same way: the endpoint will not reveal whether the email has an account.
      if (res.ok) setSent(true)
      else setNotice(res.error)
      return
    }
    const ok =
      mode === 'login'
        ? await auth.login(email, password)
        : await auth.register(email, username, password)
    if (ok) onClose()
  }

  const titles = { login: 'Sign in', register: 'Create account', forgot: 'Reset password' }

  if (mode === 'forgot' && sent) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="auth-card" onClick={(e) => e.stopPropagation()}>
          <h2 className="auth-card__title">Check your inbox</h2>
          <p className="auth-note">
            If an account uses that email, we sent a link to reset the password. It expires in 30 minutes.
          </p>
          <button className="auth-submit" onClick={onClose}>Done</button>
        </div>
      </div>
    )
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="auth-card" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-card__title">{titles[mode]}</h2>

        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            className="auth-input"
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          {mode === 'register' && (
            <input
              className="auth-input"
              type="text"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={2}
            />
          )}
          {mode !== 'forgot' && (
            <input
              className="auth-input"
              type="password"
              placeholder="Password (6+ characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
            />
          )}

          {mode === 'login' && (
            <button type="button" className="auth-link-inline" onClick={() => { setMode('forgot'); setNotice(null) }}>
              Forgot password?
            </button>
          )}

          {(auth.error || notice) && <p className="auth-error">{notice || auth.error}</p>}

          <button className="auth-submit" type="submit" disabled={auth.busy || busy}>
            {auth.busy || busy
              ? 'Working...'
              : mode === 'login'
                ? 'Sign in'
                : mode === 'register'
                  ? 'Create account'
                  : 'Send reset link'}
          </button>
        </form>

        {mode === 'forgot' ? (
          <button className="auth-toggle" onClick={() => { setMode('login'); setNotice(null) }}>
            Back to sign in
          </button>
        ) : (
          <button
            className="auth-toggle"
            onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          >
            {mode === 'login' ? 'No account? Create one' : 'Have an account? Sign in'}
          </button>
        )}
      </div>
    </div>
  )
}
