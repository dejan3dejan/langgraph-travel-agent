import { useRef, useEffect, useState } from 'react'
import './App.css'
import { useChat } from './hooks/useChat'
import { useAuth } from './hooks/useAuth'
import { useTrips } from './hooks/useTrips'
import Header from './components/Header'
import Welcome from './components/Welcome'
import Message from './components/Message'
import StatusBar from './components/StatusBar'
import InputBar from './components/InputBar'
import AuthModal from './components/AuthModal'
import Sidebar from './components/Sidebar'
import Landing from './components/Landing'
import Toast from './components/Toast'

export default function App() {
  const auth = useAuth()
  const [toast, setToast] = useState(null)
  const { messages, statuses, isStreaming, sendMessage, stopStreaming, newChat, showItinerary, loadSession, retry } = useChat({
    onItineraryDelivered: () => {
      if (auth.user) {
        setToast('Trip saved to your account.')
        setTimeout(() => setToast(null), 4000)
      }
    },
  })
  const trips = useTrips(auth.user)
  const [authOpen, setAuthOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [entered, setEntered] = useState(() => localStorage.getItem('atlas_entered') === '1')
  const chatEndRef = useRef(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, statuses])

  useEffect(() => {
    const onExpired = () => {
      setToast('Session expired. Please sign in again.')
      setTimeout(() => setToast(null), 5000)
    }
    window.addEventListener('atlas-unauthorized', onExpired)
    return () => window.removeEventListener('atlas-unauthorized', onExpired)
  }, [])

  const hasMessages = messages.length > 0
  const showRetry = !isStreaming && messages[messages.length - 1]?.isError

  // Sign out also resets the chat so the next person does not inherit the session.
  const handleSignOut = () => {
    auth.logout()
    newChat()
    setSidebarOpen(false)
  }

  const handleSelectTrip = async (trip) => {
    const detail = await trips.getDetail(trip.id)
    // Prefer resuming the full conversation so the user can keep chatting.
    if (detail?.session_id) {
      const session = await trips.getSession(detail.session_id)
      if (session) {
        loadSession(session.session_id, session.history)
        setSidebarOpen(false)
        return
      }
    }
    // Fallback: no resumable session, show the itinerary read-only.
    if (detail?.itinerary_text) {
      showItinerary(detail.itinerary_text)
      setSidebarOpen(false)
    }
  }

  if (!entered) {
    return (
      <Landing
        onEnter={() => {
          localStorage.setItem('atlas_entered', '1')
          setEntered(true)
        }}
      />
    )
  }

  return (
    <>
      <Header
        user={auth.user}
        onSignIn={() => setAuthOpen(true)}
        onSignOut={handleSignOut}
        onToggleTrips={auth.user ? () => { setSidebarOpen((o) => !o); trips.refresh() } : null}
      />

      {hasMessages && (
        <div className="toolbar">
          {showRetry && <button className="prompt-chip" onClick={retry}>Retry</button>}
          <button className="prompt-chip" onClick={newChat}>New chat</button>
        </div>
      )}

      {!hasMessages ? (
        <Welcome onPrompt={sendMessage} />
      ) : (
        <div className="chat-area">
          {messages.map((m, i) => (
            <Message key={i} role={m.role} content={m.content} isItinerary={m.isItinerary} />
          ))}
          <StatusBar statuses={statuses} />
          <div ref={chatEndRef} />
        </div>
      )}

      <InputBar
        onSend={sendMessage}
        isStreaming={isStreaming}
        onStop={stopStreaming}
      />

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
      {authOpen && <AuthModal auth={auth} onClose={() => setAuthOpen(false)} />}
      {sidebarOpen && (
        <Sidebar
          trips={trips.trips}
          loading={trips.loading}
          error={trips.error}
          onSelect={handleSelectTrip}
          onDelete={trips.remove}
          onClose={() => setSidebarOpen(false)}
        />
      )}
    </>
  )
}
