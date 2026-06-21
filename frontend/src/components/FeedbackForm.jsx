import { useState } from 'react'

// Optional star rating and optional note. Both empty is not sendable; either one is enough. The
// parent owns submission (and closing); this component just collects.
export default function FeedbackForm({ onSubmit, busy = false, placeholder = 'Anything you want to share? (optional)' }) {
  const [rating, setRating] = useState(0)
  const [message, setMessage] = useState('')
  const canSend = rating > 0 || message.trim().length > 0

  const send = () => {
    if (!canSend || busy) return
    onSubmit({ rating: rating || null, message: message.trim() || null })
  }

  return (
    <div className="feedback-form">
      <div className="feedback-stars" role="radiogroup" aria-label="Star rating">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            className={`feedback-star ${n <= rating ? 'is-on' : ''}`}
            onClick={() => setRating(n === rating ? 0 : n)}
            aria-label={`${n} star${n > 1 ? 's' : ''}`}
            aria-pressed={n <= rating}
          >
            ★
          </button>
        ))}
      </div>
      <textarea
        className="feedback-note"
        rows={3}
        placeholder={placeholder}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        maxLength={4000}
      />
      <button type="button" className="feedback-send" onClick={send} disabled={!canSend || busy}>
        {busy ? 'Sending...' : 'Send'}
      </button>
    </div>
  )
}
