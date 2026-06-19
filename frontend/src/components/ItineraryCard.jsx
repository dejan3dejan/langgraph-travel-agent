import CompassMark from './CompassMark'

// Slim reference to the itinerary that lives in the canvas, shown in the chat where the plan landed.
// On mobile it doubles as the control that brings the canvas forward.
export default function ItineraryCard({ isUpdated, summary, isActive, onView }) {
  return (
    <button type="button" className={`itinerary-card ${isActive ? 'itinerary-card--active' : ''}`} onClick={onView}>
      <span className="itinerary-card__icon"><CompassMark size={20} aria-hidden /></span>
      <span className="itinerary-card__body">
        <span className="itinerary-card__title">{isUpdated ? 'Itinerary updated' : 'Itinerary ready'}</span>
        <span className="itinerary-card__hint">{summary || 'Open it in the canvas'}</span>
      </span>
    </button>
  )
}
