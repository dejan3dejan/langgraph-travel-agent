import './Loader.css'

// A rotating wireframe globe: a static outline plus meridians that scale across to read as spin.
function Globe() {
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
      <circle cx="28" cy="28" r="22" className="loader__rim" fill="none" />
      <ellipse cx="28" cy="28" rx="22" ry="8" className="loader__lat" fill="none" />
      <line x1="6" y1="28" x2="50" y2="28" className="loader__lat" />
      <ellipse cx="28" cy="28" rx="22" ry="22" className="loader__meridian" fill="none" style={{ animationDelay: '0s' }} />
      <ellipse cx="28" cy="28" rx="22" ry="22" className="loader__meridian" fill="none" style={{ animationDelay: '-0.6s' }} />
      <ellipse cx="28" cy="28" rx="22" ry="22" className="loader__meridian loader__meridian--accent" fill="none" style={{ animationDelay: '-1.2s' }} />
    </svg>
  )
}

// A compass needle sweeping for a bearing.
function Compass() {
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
      <circle cx="28" cy="28" r="22" className="loader__rim" fill="none" />
      <g className="loader__needle">
        <polygon points="28,8 32,28 28,31 24,28" className="loader__needle-n" />
        <polygon points="28,48 32,28 28,25 24,28" className="loader__needle-s" />
      </g>
      <circle cx="28" cy="28" r="3" className="loader__cap" />
    </svg>
  )
}

const INSTRUMENTS = { globe: Globe, compass: Compass }

export default function Loader({ variant = 'globe', label = 'Charting your trip' }) {
  const Instrument = INSTRUMENTS[variant] || Globe
  return (
    <div className={`loader loader--${variant}`} role="status" aria-label={label}>
      <div className="loader__instrument">
        <Instrument />
      </div>
      <span className="loader__label">{label}</span>
    </div>
  )
}
