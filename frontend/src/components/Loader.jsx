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

// A radar sweep with a pulsing blip, for the route-mapping stage.
function Radar() {
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
      <circle cx="28" cy="28" r="22" className="loader__rim" fill="none" />
      <circle cx="28" cy="28" r="14" className="loader__lat" fill="none" />
      <circle cx="28" cy="28" r="7" className="loader__lat" fill="none" />
      <line x1="28" y1="6" x2="28" y2="50" className="loader__lat" />
      <line x1="6" y1="28" x2="50" y2="28" className="loader__lat" />
      <g className="loader__sweep">
        <path d="M28 28 L28 6 A22 22 0 0 1 47 17 Z" className="loader__sweep-wedge" />
        <line x1="28" y1="28" x2="47" y2="17" className="loader__sweep-line" />
      </g>
      <circle cx="40" cy="18" r="3" className="loader__blip" />
    </svg>
  )
}

const INSTRUMENTS = { globe: Globe, compass: Compass, radar: Radar }

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
