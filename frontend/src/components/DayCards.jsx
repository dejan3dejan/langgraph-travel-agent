import { dayColor } from '../dayColors'
import { directionsUrl } from '../maps'
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
                <a
                  className="day-card__stop-name"
                  href={directionsUrl(p)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open directions in Google Maps"
                >
                  {p.name}
                </a>
                <span className="day-card__stop-kind">{KIND_LABEL[p.kind] || 'Place'}</span>
              </li>
            ))}
          </ol>
        </article>
      ))}
    </div>
  )
}
