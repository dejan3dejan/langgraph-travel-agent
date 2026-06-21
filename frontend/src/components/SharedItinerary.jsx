import { useEffect, useState } from 'react'
import Canvas from './Canvas'
import { apiUrl } from '../api'
import './SharedItinerary.css'

// Public, read-only view of a shared itinerary snapshot. Reuses Canvas (no onShare/onRegenerate, so
// it renders just the itinerary, map and copy actions) and adds a copy-link affordance.
export default function SharedItinerary({ id }) {
  const [snapshot, setSnapshot] = useState(null)
  const [status, setStatus] = useState('loading')
  const [linkCopied, setLinkCopied] = useState(false)

  // Keep shared links out of search indexes: anyone with the link can view, but a leaked link
  // should not become a public, crawlable page.
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex,nofollow'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])

  useEffect(() => {
    let active = true
    setStatus('loading')
    fetch(apiUrl(`/api/share/${id}`))
      .then((res) => {
        if (res.status === 404) return null
        if (!res.ok) throw new Error(`Could not load shared itinerary (${res.status})`)
        return res.json()
      })
      .then((data) => {
        if (!active) return
        if (!data) { setStatus('notfound'); return }
        setSnapshot(data)
        setStatus('ready')
      })
      .catch(() => active && setStatus('error'))
    return () => { active = false }
  }, [id])

  const copyLink = async () => {
    await navigator.clipboard.writeText(window.location.href)
    setLinkCopied(true)
    setTimeout(() => setLinkCopied(false), 2000)
  }

  if (status === 'loading') {
    return <div className="shared shared--message">Loading shared itinerary...</div>
  }

  if (status !== 'ready') {
    const message =
      status === 'notfound'
        ? 'This shared itinerary was not found. The link may be wrong or it was removed.'
        : 'Something went wrong loading this itinerary. Please try again.'
    return (
      <div className="shared shared--message">
        <p>{message}</p>
        <a className="shared__cta" href={window.location.origin}>Plan your own trip</a>
      </div>
    )
  }

  return (
    <div className="shared">
      <div className="shared__bar">
        <span className="shared__brand">Shared with you via Atlas</span>
        <div className="shared__actions">
          <button type="button" className="shared__link" onClick={copyLink}>
            {linkCopied ? 'Link copied' : 'Copy link'}
          </button>
          <a className="shared__cta" href={window.location.origin}>Plan your own trip</a>
        </div>
      </div>
      <div className="shared__canvas">
        <Canvas itinerary={{ content: snapshot.itinerary_text }} geo={snapshot.geo} />
      </div>
    </div>
  )
}
