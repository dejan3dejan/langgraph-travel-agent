import { useEffect } from 'react'
import CompassMark from './CompassMark'
import { track, events } from '../analytics'

// Marketing landing shown on first load. Copy is plain placeholder, pending the marketing pass.
export default function Landing({ onEnter }) {
  useEffect(() => {
    track(events.LANDING_VIEWED)
  }, [])

  return (
    <div className="landing">
      <div className="landing__hero">
        <span className="landing__badge"><CompassMark size={56} aria-hidden /></span>
        <h1 className="landing__title">
          Plan trips with <em>Atlas</em>
        </h1>
        <p className="landing__sub">
          A multi-agent travel planner that researches real spots, geocodes them, and builds a
          logistics-aware, day-by-day itinerary.
        </p>
        <button className="landing__cta" onClick={onEnter}>Start planning</button>
      </div>

      <div className="landing__features">
        <div className="feature-card">
          <span className="feature-card__icon">🤖</span>
          <h3 className="feature-card__title">Multi-agent planning</h3>
          <p className="feature-card__text">
            Specialized agents research food, activities, and stays in parallel, then a critic
            reviews the plan.
          </p>
        </div>
        <div className="feature-card">
          <span className="feature-card__icon">🗺️</span>
          <h3 className="feature-card__title">Logistics-aware routing</h3>
          <p className="feature-card__text">
            Every place is geocoded and grouped by proximity, so each day flows without
            backtracking across the city.
          </p>
        </div>
        <div className="feature-card">
          <span className="feature-card__icon">💾</span>
          <h3 className="feature-card__title">Saved trips</h3>
          <p className="feature-card__text">
            Create an account to keep your itineraries and pick up where you left off.
          </p>
        </div>
      </div>
    </div>
  )
}
