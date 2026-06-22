export default function ConsentBanner({ onAccept, onDecline }) {
  return (
    <div className="consent-banner" role="dialog" aria-label="Analytics consent">
      <span className="consent-banner__text">
        We use privacy-friendly analytics to improve Atlas. Is it ok to turn them on?
      </span>
      <div className="consent-banner__actions">
        <button className="consent-banner__cta" onClick={onAccept}>Accept</button>
        <button className="consent-banner__decline" onClick={onDecline}>Decline</button>
      </div>
    </div>
  )
}
