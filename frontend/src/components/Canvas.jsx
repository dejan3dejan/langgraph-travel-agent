import { lazy, Suspense, useState } from 'react'
import Message from './Message'
import DayCards from './DayCards'
import './Canvas.css'

// Leaflet is heavy and only needed once a plan exists, so keep it off the first-paint bundle.
const Map = lazy(() => import('./Map'))

// The persistent artifact pane. The title and map stay pinned at the top while the itinerary text
// and day cards scroll underneath, so the map never scrolls out of reach.
export default function Canvas({ itinerary, geo, onRegenerate, isStreaming }) {
  const heading = itinerary?.content?.match(/^#\s+(.+)$/m)?.[1]
  const title = heading || 'Your itinerary'
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    if (!itinerary?.content) return
    await navigator.clipboard.writeText(itinerary.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="canvas">
      <header className="canvas__header">
        <h2 className="canvas__title">{title}</h2>
        {itinerary && onRegenerate && (
          <button
            type="button"
            className="canvas__action"
            onClick={onRegenerate}
            disabled={isStreaming}
            title="Build a fresh plan from scratch"
          >
            {isStreaming ? 'Regenerating' : 'Regenerate'}
          </button>
        )}
        {itinerary && (
          <button type="button" className="canvas__action" onClick={copy} title="Copy itinerary">
            {copied ? 'Copied' : 'Copy'}
          </button>
        )}
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
