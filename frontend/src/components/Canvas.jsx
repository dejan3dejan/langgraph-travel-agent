import { lazy, Suspense } from 'react'
import Message from './Message'
import DayCards from './DayCards'
import './Canvas.css'

// Leaflet is heavy and only needed once a plan exists, so keep it off the first-paint bundle.
const Map = lazy(() => import('./Map'))

// The persistent artifact pane: the itinerary and its map stay put here instead of scrolling away
// in the chat. One itinerary at a time, the latest delivered plan.
export default function Canvas({ itinerary, geo }) {
  return (
    <div className="canvas">
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
      <Suspense fallback={null}>
        <Map geo={geo} />
      </Suspense>
    </div>
  )
}
