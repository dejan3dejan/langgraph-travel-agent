import { useState } from 'react'

function tripMeta(t) {
  return (
    [t.duration, t.budget].filter(Boolean).join(' · ') +
    (t.created_at ? `${t.duration || t.budget ? ' · ' : ''}${new Date(t.created_at).toLocaleDateString()}` : '')
  )
}

// Owner-only control for inviting a registered user to a trip. Collapsed by default so the trip
// list stays scannable; the role defaults to viewer, the safer grant.
function InviteControl({ tripId, onInvite }) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('viewer')

  if (!open) {
    return (
      <button className="trip-item__share" onClick={() => setOpen(true)} aria-label="Share trip">
        Share
      </button>
    )
  }

  const submit = (e) => {
    e.preventDefault()
    const trimmed = email.trim()
    if (!trimmed) return
    onInvite(tripId, trimmed, role)
    setEmail('')
    setOpen(false)
  }

  return (
    <form className="invite" onSubmit={submit}>
      <input
        className="invite__email"
        type="email"
        placeholder="Collaborator email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <div className="invite__row">
        <label className="invite__role">
          Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="viewer">Viewer</option>
            <option value="editor">Editor</option>
          </select>
        </label>
        <button className="invite__send" type="submit">Invite</button>
      </div>
    </form>
  )
}

// Saved trips the user owns, plus a separate section for trips others have shared with them. Shared
// trips carry the owner and the granted role so they read clearly as not-yours.
export default function Sidebar({ trips, sharedTrips = [], loading, error, onSelect, onDelete, onInvite, onClose }) {
  return (
    <aside className="sidebar">
      <div className="sidebar__head">
        <span className="sidebar__title">Saved trips</span>
        <button className="sidebar__close" onClick={onClose} aria-label="Close sidebar">×</button>
      </div>

      {loading && <p className="sidebar__empty">Loading...</p>}
      {error && <p className="sidebar__error">{error}</p>}
      {!loading && !error && trips.length === 0 && (
        <p className="sidebar__empty">No saved trips yet. Plan one and it shows up here.</p>
      )}

      <ul className="sidebar__list">
        {trips.map((t) => (
          <li key={t.id} className="trip-item trip-item--owned">
            <div className="trip-item__row">
              <button className="trip-item__main" onClick={() => onSelect(t)}>
                <span className="trip-item__dest">{t.destination || 'Trip'}</span>
                <span className="trip-item__meta">{tripMeta(t)}</span>
              </button>
              <button className="trip-item__del" onClick={() => onDelete(t.id)} aria-label="Delete trip">
                ×
              </button>
            </div>
            {onInvite && <InviteControl tripId={t.id} onInvite={onInvite} />}
          </li>
        ))}
      </ul>

      {sharedTrips.length > 0 && (
        <>
          <span className="sidebar__title sidebar__title--sub">Shared with you</span>
          <ul className="sidebar__list">
            {sharedTrips.map((t) => (
              <li key={t.id} className="trip-item">
                <button className="trip-item__main" onClick={() => onSelect(t)}>
                  <span className="trip-item__dest">{t.destination || 'Trip'}</span>
                  <span className="trip-item__meta">{tripMeta(t)}</span>
                  <span className="trip-item__badge">{t.owner} · {t.role}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  )
}
