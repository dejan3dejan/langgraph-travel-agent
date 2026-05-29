import { motion, AnimatePresence } from 'framer-motion'

export default function StatusBar({ statuses }) {
  if (!statuses.length) return null

  return (
    <div className="status-strip">
      <AnimatePresence mode="popLayout">
        {statuses.map((s) => (
          <motion.div
            key={s.node}
            className={`status-pill status-pill--${s.state}`}
            initial={{ opacity: 0, scale: 0.8, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.8 }}
            transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            layout
          >
            <span className="status-pill__dot" />
            {s.label}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
