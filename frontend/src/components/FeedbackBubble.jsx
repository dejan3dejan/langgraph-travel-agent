// A small dismissible card that hosts a feedback form. Shown one at a time and never auto-repeated,
// so it stays a gentle bubble rather than a nag.
export default function FeedbackBubble({ title, onClose, children }) {
  return (
    <div className="feedback-bubble" role="dialog" aria-label={title}>
      <div className="feedback-bubble__head">
        <span className="feedback-bubble__title">{title}</span>
        <button type="button" className="feedback-bubble__close" onClick={onClose} aria-label="Dismiss">
          ×
        </button>
      </div>
      {children}
    </div>
  )
}
