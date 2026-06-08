export default function Sidebar({ trips, loading, error, onSelect, onDelete, onClose }) {
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
          <li key={t.id} className="trip-item">
            <button className="trip-item__main" onClick={() => onSelect(t)}>
              <span className="trip-item__dest">{t.destination || 'Trip'}</span>
              <span className="trip-item__meta">
                {[t.duration, t.budget].filter(Boolean).join(' · ')}
                {t.created_at ? ` · ${new Date(t.created_at).toLocaleDateString()}` : ''}
              </span>
            </button>
            <button className="trip-item__del" onClick={() => onDelete(t.id)} aria-label="Delete trip">
              ×
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
