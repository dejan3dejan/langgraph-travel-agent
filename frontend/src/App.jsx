import { useRef, useEffect, useState } from 'react'
import './App.css'
import { useChat } from './hooks/useChat'
import { useAuth } from './hooks/useAuth'
import { useTrips } from './hooks/useTrips'
import Header from './components/Header'
import Welcome from './components/Welcome'
import Message from './components/Message'
import InputBar from './components/InputBar'
import AuthModal from './components/AuthModal'
import Sidebar from './components/Sidebar'
import Landing from './components/Landing'
import Toast from './components/Toast'
import SignupPrompt from './components/SignupPrompt'
import Loader from './components/Loader'
import Canvas from './components/Canvas'
import ItineraryCard from './components/ItineraryCard'

export default function App() {
  const auth = useAuth()
  const [toast, setToast] = useState(null)
  const [signupPrompt, setSignupPrompt] = useState(false)
  // On mobile the split collapses to one column; this picks which one is showing.
  const [mobileView, setMobileView] = useState('chat')
  // Which itinerary the canvas is showing; null follows the latest, an index pins an older version.
  const [viewedItineraryIndex, setViewedItineraryIndex] = useState(null)
  // Nudge an anonymous user to sign up once per conversation, not on every regenerate, and never
  // after they dismiss it. Resets when a new chat clears the messages.
  const signupNudgedRef = useRef(false)
  const { messages, isStreaming, itineraryGeo, planningStage, sendMessage, stopStreaming, newChat, showItinerary, loadSession, retry, regenerate } = useChat({
    onItineraryDelivered: ({ isEdit } = {}) => {
      // A delivered plan is the thing to look at, so surface the canvas on mobile and follow it.
      setMobileView('canvas')
      setViewedItineraryIndex(null)
      if (auth.user) {
        setToast(isEdit ? 'Trip updated.' : 'Trip saved to your account.')
        setTimeout(() => setToast(null), 4000)
      } else if (!isEdit && !signupNudgedRef.current) {
        // Nudge signup once per conversation, not on every fresh plan (regenerate) or follow-up edit.
        signupNudgedRef.current = true
        setSignupPrompt(true)
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
  }, [messages, planningStage])

  // A new chat (or sign-out) clears the messages, so let the next plan nudge signup again.
  useEffect(() => {
    if (messages.length === 0) signupNudgedRef.current = false
  }, [messages.length])

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
  // The dead air between sending and the first streamed token: research, logistics, compile.
  const planning = isStreaming && !messages.some((m) => m.role === 'ai-stream')

  // The presence of an itinerary is what splits the view. The canvas follows the latest by default,
  // but an older ItineraryCard can pin its own version back into the canvas.
  let latestItineraryIndex = -1
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].isItinerary) { latestItineraryIndex = i; break }
  }
  const split = latestItineraryIndex >= 0
  const viewedIndex = messages[viewedItineraryIndex]?.isItinerary ? viewedItineraryIndex : latestItineraryIndex
  const viewedItinerary = split ? messages[viewedIndex] : null

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
        loadSession(session.session_id, session.history, detail.geo)
        setSidebarOpen(false)
        return
      }
    }
    // Fallback: no resumable session, show the itinerary read-only.
    if (detail?.itinerary_text) {
      showItinerary(detail.itinerary_text, detail.geo)
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

  const chatScroll = (
    <div className="chat-area">
      {messages.map((m, i) =>
        m.isItinerary ? (
          <ItineraryCard
            key={i}
            isUpdated={m.isUpdated}
            summary={m.updatedSummary}
            isActive={i === viewedIndex}
            onView={() => { setViewedItineraryIndex(i); setMobileView('canvas') }}
          />
        ) : (
          <Message key={i} role={m.role} content={m.content} isItinerary={m.isItinerary} isUpdated={m.isUpdated} updatedSummary={m.updatedSummary} />
        ),
      )}
      {planning && (
        <Loader variant={planningStage?.variant || 'compass'} label={planningStage?.line || 'Charting your trip'} />
      )}
      <div ref={chatEndRef} />
    </div>
  )

  const inputBar = <InputBar onSend={sendMessage} isStreaming={isStreaming} onStop={stopStreaming} />

  return (
    <div className={`app ${split ? 'app--split' : ''}`}>
      <Header
        user={auth.user}
        onSignIn={() => setAuthOpen(true)}
        onSignOut={handleSignOut}
        onToggleTrips={auth.user ? () => { setSidebarOpen((o) => !o); trips.refresh() } : null}
      />

      {hasMessages && (
        <div className="toolbar">
          {split && (
            <div className="view-toggle">
              <button className={`view-toggle__btn ${mobileView === 'chat' ? 'is-active' : ''}`} onClick={() => setMobileView('chat')}>Chat</button>
              <button className={`view-toggle__btn ${mobileView === 'canvas' ? 'is-active' : ''}`} onClick={() => setMobileView('canvas')}>Itinerary</button>
            </div>
          )}
          {showRetry && <button className="prompt-chip" onClick={retry}>Retry</button>}
          <button className="prompt-chip" onClick={newChat}>New chat</button>
        </div>
      )}

      {!hasMessages ? (
        <Welcome onPrompt={sendMessage} />
      ) : split ? (
        <div className="workspace">
          <div className={`workspace__chat ${mobileView === 'chat' ? 'is-active' : ''}`}>
            {chatScroll}
            {inputBar}
          </div>
          <div className={`workspace__canvas ${mobileView === 'canvas' ? 'is-active' : ''}`}>
            <Canvas itinerary={viewedItinerary} geo={itineraryGeo} onRegenerate={regenerate} isStreaming={isStreaming} />
          </div>
        </div>
      ) : (
        chatScroll
      )}

      {/* In the split, the input lives inside the chat column; everywhere else it sits at the bottom. */}
      {!split && inputBar}

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
      {signupPrompt && !auth.user && (
        <SignupPrompt
          onSignUp={() => { setSignupPrompt(false); setAuthOpen(true) }}
          onDismiss={() => setSignupPrompt(false)}
        />
      )}
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
    </div>
  )
}
