import { dayColor } from '../dayColors'
import './DayCards.css'

// Short tag per stop type so a day reads at a glance.
const KIND_LABEL = { activity: 'Activity', restaurant: 'Food', place: 'Place' }

export default function DayCards({ geo }) {
  if (!geo || !geo.days || geo.days.length === 0) return null

  return (
    <div className="day-cards">
      {geo.days.map((d) => (
        <article key={d.day} className="day-card">
          <header className="day-card__head">
            <span className="day-card__badge" style={{ background: dayColor(d.day) }}>{d.day}</span>
            <h3 className="day-card__title">{d.title || d.label || `Day ${d.day}`}</h3>
          </header>
          <ol className="day-card__stops">
            {d.places.map((p, i) => (
              <li key={i} className="day-card__stop">
                <span className="day-card__stop-name">{p.name}</span>
                <span className="day-card__stop-kind">{KIND_LABEL[p.kind] || 'Place'}</span>
              </li>
            ))}
          </ol>
        </article>
      ))}
    </div>
  )
}
