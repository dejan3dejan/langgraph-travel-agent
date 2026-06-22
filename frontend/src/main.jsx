import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import SharedItinerary from './components/SharedItinerary.jsx'
import ResetPassword from './components/ResetPassword.jsx'
import VerifyEmail from './components/VerifyEmail.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'

// apply the saved theme before first paint to avoid a flash
if (localStorage.getItem('theme') === 'dark') {
  document.documentElement.setAttribute('data-theme', 'dark')
}

// The app has no router, so a few query params read on load are the whole routing story:
// ?share=<id> opens the public read-only view, ?reset=<token> the password-reset form, and
// ?verify=<token> the email-verification page.
const params = new URLSearchParams(window.location.search)
const shareId = params.get('share')
const resetToken = params.get('reset')
const verifyToken = params.get('verify')

function Root() {
  if (shareId) return <SharedItinerary id={shareId} />
  if (resetToken) return <ResetPassword token={resetToken} />
  if (verifyToken) return <VerifyEmail token={verifyToken} />
  return <App />
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <Root />
    </ErrorBoundary>
  </StrictMode>,
)
