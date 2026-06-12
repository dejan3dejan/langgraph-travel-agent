import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

export default function Message({ role, content, isItinerary, isUpdated }) {
  const isUser = role === 'user'
  const isStream = role === 'ai-stream'
  // Render markdown only for a finalized itinerary. While streaming we show plain text with
  // newlines preserved and switch to formatted markdown on completion, so partial markdown never
  // renders malformed mid-stream.
  const showMarkdown = !isUser && isItinerary && !isStream

  return (
    <motion.div
      className={`message message--${isUser ? 'user' : 'ai'} ${showMarkdown ? 'message--itinerary' : ''}`}
      variants={variants}
      initial="hidden"
      animate="visible"
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      layout
    >
      <div className="message__avatar">
        {isUser ? '✦' : '🧭'}
      </div>
      <div className="message__bubble">
        {showMarkdown ? (
          <div className="markdown-body">
            {isUpdated && <span className="updated-badge">Updated</span>}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
            <p className="estimate-note">Prices and availability are estimates, not live quotes.</p>
          </div>
        ) : (
          <span className={isStream ? 'stream-text' : undefined}>
            {content}
            {isStream && <span className="cursor-blink">|</span>}
          </span>
        )}
      </div>
    </motion.div>
  )
}
