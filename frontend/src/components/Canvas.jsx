import { lazy, Suspense, useState, useRef } from 'react'
import Message from './Message'
import DayCards from './DayCards'
import './Canvas.css'

// Leaflet is heavy and only needed once a plan exists, so keep it off the first-paint bundle.
const Map = lazy(() => import('./Map'))

function RefreshIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function StarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

function ShareIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  )
}

function UnshareIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18.84 12.25 21 10.06a5 5 0 0 0-7.07-7.07L11.75 5.16" />
      <path d="M5.17 11.75 3 13.94a5 5 0 0 0 7.07 7.07l2.18-2.18" />
      <line x1="2" y1="2" x2="22" y2="22" />
    </svg>
  )
}

const SHARE_LABEL = { sharing: 'Sharing', copied: 'Link copied', error: 'Share failed' }

// The persistent artifact pane. The title and map stay pinned at the top while the itinerary text
// and day cards scroll underneath, so the map never scrolls out of reach.
export default function Canvas({ itinerary, geo, onRegenerate, isStreaming, onShare, shareStatus = 'idle', onUnshare, isShared = false, onAddToChat, variant, onSelectVariant, onKeepVariant, onRate }) {
  const comparing = !!variant
  const heading = itinerary?.content?.match(/^#\s+(.+)$/m)?.[1]
  const title = heading || 'Your itinerary'
  const [copied, setCopied] = useState(false)
  const detailsRef = useRef(null)
  // The current text selection inside the itinerary body, with where to float its action button.
  const [selection, setSelection] = useState(null)

  const copy = async () => {
    if (!itinerary?.content) return
    await navigator.clipboard.writeText(itinerary.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Surface an "add to chat" button when the user highlights a chunk of the itinerary, so the next
  // message can quote that section. Only act on selections that live inside the scrolling body.
  const handleSelect = () => {
    if (!onAddToChat) return
    const sel = window.getSelection()
    const text = sel?.toString().trim()
    const container = detailsRef.current
    if (!text || !sel.rangeCount || !container || !container.contains(sel.anchorNode)) {
      setSelection(null)
      return
    }
    const rangeRect = sel.getRangeAt(0).getBoundingClientRect()
    const box = container.getBoundingClientRect()
    setSelection({
      text,
      top: rangeRect.bottom - box.top + container.scrollTop,
      left: rangeRect.left - box.left,
    })
  }

  const addToChat = () => {
    if (selection) onAddToChat(selection.text)
    setSelection(null)
    window.getSelection()?.removeAllRanges()
  }

  // Lazy-load the export pipeline on click so it stays off the first-paint bundle. The itinerary is
  // already rendered to HTML by react-markdown (no raw HTML pass), so reuse that DOM for the PDF body.
  const exportPdf = async () => {
    if (!itinerary?.content) return
    const bodyHtml = detailsRef.current?.querySelector('.markdown-body')?.innerHTML || ''
    const { exportItineraryPdf } = await import('../export/itineraryPdf')
    exportItineraryPdf({ title, bodyHtml, geo })
  }

  return (
    <div className="canvas">
      <header className="canvas__header">
        <h2 className="canvas__title">{title}</h2>
        {comparing && (
          <div className="canvas__compare">
            <div className="canvas__variant-toggle" role="group" aria-label="Compare itineraries">
              <button
                type="button"
                className={`canvas__variant-btn ${variant === 'A' ? 'is-active' : ''}`}
                onClick={() => onSelectVariant('A')}
                aria-pressed={variant === 'A'}
              >
                Option A
              </button>
              <button
                type="button"
                className={`canvas__variant-btn ${variant === 'B' ? 'is-active' : ''}`}
                onClick={() => onSelectVariant('B')}
                aria-pressed={variant === 'B'}
              >
                Option B
              </button>
            </div>
            <button
              type="button"
              className="canvas__keep"
              onClick={() => onKeepVariant(variant)}
              disabled={isStreaming}
              title="Keep this itinerary and discard the other"
            >
              Keep this one
            </button>
          </div>
        )}
        {!comparing && itinerary && onRegenerate && (
          <button
            type="button"
            className={`canvas__action ${isStreaming ? 'canvas__action--busy' : ''}`}
            onClick={onRegenerate}
            disabled={isStreaming}
            aria-label={isStreaming ? 'Regenerating' : 'Regenerate'}
            title="Build a fresh plan from scratch"
          >
            <RefreshIcon />
          </button>
        )}
        {!comparing && itinerary && (
          <button
            type="button"
            className="canvas__action"
            onClick={copy}
            aria-label={copied ? 'Copied' : 'Copy'}
            title="Copy itinerary"
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
          </button>
        )}
        {!comparing && itinerary && (
          <button
            type="button"
            className="canvas__action"
            onClick={exportPdf}
            aria-label="Export PDF"
            title="Download a printable PDF"
          >
            <DownloadIcon />
          </button>
        )}
        {!comparing && itinerary && onRate && (
          <button
            type="button"
            className="canvas__action"
            onClick={onRate}
            aria-label="Rate this plan"
            title="Rate this plan"
          >
            <StarIcon />
          </button>
        )}
        {!comparing && itinerary && onShare && (
          <button
            type="button"
            className="canvas__action"
            onClick={onShare}
            disabled={shareStatus === 'sharing'}
            aria-label={SHARE_LABEL[shareStatus] || 'Share'}
            title="Copy a public link to this itinerary"
          >
            {shareStatus === 'copied' ? <CheckIcon /> : <ShareIcon />}
          </button>
        )}
        {!comparing && itinerary && onShare && onUnshare && isShared && (
          <button
            type="button"
            className="canvas__action"
            onClick={onUnshare}
            aria-label="Stop sharing"
            title="Revoke the public link"
          >
            <UnshareIcon />
          </button>
        )}
      </header>

      <div className="canvas__map">
        <Suspense fallback={null}>
          <Map geo={geo} />
        </Suspense>
      </div>

      <div
        className="canvas__details"
        ref={detailsRef}
        onMouseUp={handleSelect}
        onKeyUp={handleSelect}
        onScroll={() => selection && setSelection(null)}
      >
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
        {selection && (
          <button
            type="button"
            className="canvas__quote-btn"
            style={{ top: selection.top, left: selection.left }}
            onClick={addToChat}
          >
            Add to chat
          </button>
        )}
      </div>
    </div>
  )
}
