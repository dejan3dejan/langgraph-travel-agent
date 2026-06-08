export default function SignupPrompt({ onSignUp, onDismiss }) {
  return (
    <div className="signup-prompt" role="status">
      <span>Sign up to save this trip and pick up where you left off.</span>
      <div className="signup-prompt__actions">
        <button className="signup-prompt__cta" onClick={onSignUp}>Sign up</button>
        <button className="signup-prompt__dismiss" onClick={onDismiss} aria-label="Dismiss">
          ×
        </button>
      </div>
    </div>
  )
}
