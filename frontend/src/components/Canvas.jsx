import { lazy, Suspense } from 'react'
import Message from './Message'
import DayCards from './DayCards'
import './Canvas.css'

// Leaflet is heavy and only needed once a plan exists, so keep it off the first-paint bundle.
const Map = lazy(() => import('./Map'))

// The persistent artifact pane. The title and map stay pinned at the top while the itinerary text
// and day cards scroll underneath, so the map never scrolls out of reach.
export default function Canvas({ itinerary, geo }) {
  const heading = itinerary?.content?.match(/^#\s+(.+)$/m)?.[1]
  const title = heading || 'Your itinerary'

  return (
    <div className="canvas">
      <header className="canvas__header">
        <h2 className="canvas__title">{title}</h2>
      </header>

      <div className="canvas__map">
        <Suspense fallback={null}>
          <Map geo={geo} />
        </Suspense>
      </div>

      <div className="canvas__details">
        {itinerary && (
          <Message
            role="ai"
            content={itinerary.content}
            isItinerary
            isUpdated={itinerary.isUpdated}
            updatedSummary={itinerary.updatedSummary}
          />
        )}
        {geo && <DayCards geo={geo} />}
      </div>
    </div>
  )
}
