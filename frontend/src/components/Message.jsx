import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

function looksLikeItinerary(text) {
  return text.includes('## Day') || (text.includes('# ') && text.includes('Trip to'))
}

export default function Message({ role, content, isItinerary }) {
  const isUser = role === 'user'
  const isStream = role === 'ai-stream'
  // Finalized AI messages carry an explicit is_itinerary flag from the backend.
  // While streaming we don't have it yet, so fall back to a content heuristic.
  const showMarkdown = !isUser && (isItinerary || (isStream && looksLikeItinerary(content)))

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
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
            {isStream && <span className="cursor-blink">|</span>}
          </div>
        ) : (
          <>
            {content}
            {isStream && <span className="cursor-blink">|</span>}
          </>
        )}
      </div>
    </motion.div>
  )
}
