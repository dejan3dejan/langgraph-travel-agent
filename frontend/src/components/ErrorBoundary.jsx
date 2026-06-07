import { Component } from 'react'

// Error boundaries have no hook equivalent — catching render-time crashes requires a
// class component. This wraps the whole app so a thrown render error shows a recoverable
// panel instead of a blank screen.
export default class ErrorBoundary extends Component {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error('Atlas UI error:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="error-boundary">
        <div className="error-card">
          <div className="error-card__icon">⚠</div>
          <h2 className="error-card__title">Something broke on our end</h2>
          <p className="error-card__msg">
            Atlas hit an unexpected error. A reload usually clears it.
          </p>
          <button className="error-card__btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
