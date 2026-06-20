import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import SharedItinerary from './components/SharedItinerary.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'

// apply the saved theme before first paint to avoid a flash
if (localStorage.getItem('theme') === 'dark') {
  document.documentElement.setAttribute('data-theme', 'dark')
}

// A ?share=<id> link opens the public read-only view instead of the app. The app has no router, so
// this query param read on load is the whole routing story.
const shareId = new URLSearchParams(window.location.search).get('share')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      {shareId ? <SharedItinerary id={shareId} /> : <App />}
    </ErrorBoundary>
  </StrictMode>,
)
