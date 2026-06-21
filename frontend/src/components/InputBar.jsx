import { useState, useRef, useEffect } from 'react'
import { buildQuotedMessage } from '../quote'

export default function InputBar({ onSend, isStreaming, onStop, quote, onClearQuote, showCompare = false, compareMode = false, onToggleCompare }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!isStreaming) textareaRef.current?.focus()
  }, [isStreaming])

  const handleSubmit = () => {
    if (isStreaming) {
      onStop()
      return
    }
    if (!text.trim()) return
    onSend(buildQuotedMessage(quote, text.trim()))
    setText('')
    onClearQuote?.()
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleInput = (e) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  }

  return (
    <div className="input-bar">
      {showCompare && (
        <button
          type="button"
          className={`compare-toggle ${compareMode ? 'is-on' : ''}`}
          onClick={onToggleCompare}
          aria-pressed={compareMode}
          title="Plan two itineraries side by side and pick your favorite"
        >
          Compare two options
        </button>
      )}
      {quote && (
        <div className="input-quote">
          <span className="input-quote__label">Editing</span>
          <span className="input-quote__text">{quote}</span>
          <button
            type="button"
            className="input-quote__remove"
            onClick={onClearQuote}
            aria-label="Remove quoted selection"
          >
            ×
          </button>
        </div>
      )}
      <div className="input-row">
        <textarea
          ref={textareaRef}
          className="input-field"
          rows={1}
          placeholder={isStreaming ? 'Atlas is planning...' : 'Tell me about your dream trip...'}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
        />
        <button
          className="send-btn"
          onClick={handleSubmit}
          disabled={!isStreaming && !text.trim()}
          title={isStreaming ? 'Stop' : 'Send'}
        >
          {isStreaming ? '◼' : '↑'}
        </button>
      </div>
    </div>
  )
}
