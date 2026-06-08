import { useState } from 'react'

export default function Header({ user, onSignIn, onSignOut }) {
  const [theme, setTheme] = useState(
    () => document.documentElement.getAttribute('data-theme') || 'light',
  )

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    if (next === 'dark') document.documentElement.setAttribute('data-theme', 'dark')
    else document.documentElement.removeAttribute('data-theme')
    localStorage.setItem('theme', next)
    setTheme(next)
  }

  return (
    <header className="header">
      <div className="auth-control">
        {user ? (
          <>
            <span className="auth-user">{user.username}</span>
            <button className="auth-link" onClick={onSignOut}>Sign out</button>
          </>
        ) : (
          <button className="auth-link" onClick={onSignIn}>Sign in</button>
        )}
      </div>

      <div className="logo-row">
        <span className="compass">🧭</span>
        <span className="logo-text">Atlas</span>
      </div>
      <p className="tagline">Your cartographer for the world</p>

      <button
        className="theme-toggle"
        onClick={toggleTheme}
        aria-label="Toggle dark mode"
        title="Toggle theme"
      >
        {theme === 'dark' ? '☀️' : '🌙'}
      </button>
    </header>
  )
}
