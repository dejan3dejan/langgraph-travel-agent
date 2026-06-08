import { useState } from 'react'

export default function AuthModal({ auth, onClose }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    const ok =
      mode === 'login'
        ? await auth.login(email, password)
        : await auth.register(email, username, password)
    if (ok) onClose()
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="auth-card" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-card__title">{mode === 'login' ? 'Sign in' : 'Create account'}</h2>

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
          <input
            className="auth-input"
            type="password"
            placeholder="Password (6+ characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />

          {auth.error && <p className="auth-error">{auth.error}</p>}

          <button className="auth-submit" type="submit" disabled={auth.busy}>
            {auth.busy ? 'Working...' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <button
          className="auth-toggle"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
        >
          {mode === 'login' ? 'No account? Create one' : 'Have an account? Sign in'}
        </button>
      </div>
    </div>
  )
}
