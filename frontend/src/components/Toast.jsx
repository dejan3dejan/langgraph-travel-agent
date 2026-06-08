export default function Toast({ message, onClose }) {
  return (
    <div className="toast" role="status">
      <span>{message}</span>
      <button className="toast__close" onClick={onClose} aria-label="Dismiss">
        ×
      </button>
    </div>
  )
}
