import { useRef, useEffect, useState } from 'react'
import './App.css'
import { useChat } from './hooks/useChat'
import { useAuth } from './hooks/useAuth'
import { useTrips } from './hooks/useTrips'
import { useShare } from './hooks/useShare'
import { useFeedback } from './hooks/useFeedback'
import { useProfile } from './hooks/useProfile'
import Header from './components/Header'
import Welcome from './components/Welcome'
import Intake from './components/Intake'
import Message from './components/Message'
import InputBar from './components/InputBar'
import AuthModal from './components/AuthModal'
import AccountSettings from './components/AccountSettings'
import Sidebar from './components/Sidebar'
import Landing from './components/Landing'
import Toast from './components/Toast'
import SignupPrompt from './components/SignupPrompt'
import Loader from './components/Loader'
import Canvas from './components/Canvas'
import ItineraryCard from './components/ItineraryCard'
import FeedbackBubble from './components/FeedbackBubble'
import FeedbackForm from './components/FeedbackForm'
import ConsentBanner from './components/ConsentBanner'
import { useConsent } from './consent'

export default function App() {
  const auth = useAuth()
  const [toast, setToast] = useState(null)
  const [signupPrompt, setSignupPrompt] = useState(false)
  // On mobile the split collapses to one column; this picks which one is showing.
  const [mobileView, setMobileView] = useState('chat')
  // Which itinerary the canvas is showing; null follows the latest, an index pins an older version.
  const [viewedItineraryIndex, setViewedItineraryIndex] = useState(null)
  // A chunk of the itinerary the user picked to quote into their next message; null when none.
  const [pendingQuote, setPendingQuote] = useState(null)
  // Opt-in: when on, a fresh plan request asks the backend for two variants to compare.
  const [compareMode, setCompareMode] = useState(false)
  // A feedback bubble/panel to show, or null. { kind, title, placeholder, context }.
  const [feedbackTarget, setFeedbackTarget] = useState(null)
  // Nudge an anonymous user to sign up once per conversation, not on every regenerate, and never
  // after they dismiss it. Resets when a new chat clears the messages.
  const signupNudgedRef = useRef(false)
  // The gentle rating bubble appears at most once per conversation, and never on the same delivery
  // as the signup nudge, so the user is never stacked with two prompts.
  const ratingNudgedRef = useRef(false)
  const { messages, isStreaming, itineraryGeo, planningStage, variants, activeVariant, selectVariant, keepVariant, sessionId, sendMessage, stopStreaming, newChat, showItinerary, loadSession, retry, regenerate } = useChat({
    onItineraryDelivered: ({ isEdit, fromCompare, chosen } = {}) => {
      // A delivered plan is the thing to look at, so surface the canvas on mobile and follow it.
      setMobileView('canvas')
      setViewedItineraryIndex(null)
      const willNudgeSignup = !auth.user && !isEdit && !signupNudgedRef.current
      if (auth.user) {
        setToast(isEdit ? 'Trip updated.' : 'Trip saved to your account.')
        setTimeout(() => setToast(null), 4000)
      } else if (willNudgeSignup) {
        // Nudge signup once per conversation, not on every fresh plan (regenerate) or follow-up edit.
        signupNudgedRef.current = true
        setSignupPrompt(true)
      }
      // Offer a one-time, dismissible rating bubble for a fresh plan, but not alongside the signup
      // nudge. The compare case asks why this option, tagged with which variant was kept.
      if (!isEdit && !willNudgeSignup && !ratingNudgedRef.current) {
        ratingNudgedRef.current = true
        setFeedbackTarget(
          fromCompare
            ? { kind: 'compare', title: 'Why this option?', placeholder: 'What made this one the keeper? (optional)', context: { chosen } }
            : { kind: 'plan', title: 'How was this plan?', placeholder: 'Anything you liked or would change? (optional)' },
        )
      }
    },
  })
  const trips = useTrips(auth.user)
  const share = useShare()
  const feedback = useFeedback()
  const profile = useProfile(auth.user)
  const consent = useConsent()
  const [authOpen, setAuthOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [entered, setEntered] = useState(() => localStorage.getItem('atlas_entered') === '1')
  const chatEndRef = useRef(null)

  // Two streamed itinerary variants waiting to be compared and chosen between.
  const comparing = !!variants

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, planningStage])

  // When the compare view opens, surface the canvas on mobile so the variants are visible.
  useEffect(() => {
    if (comparing) setMobileView('canvas')
  }, [comparing])

  // A new chat (or sign-out) clears the messages, so let the next plan nudge signup again and drop
  // any selection staged for quoting, which belongs to the conversation that just ended.
  useEffect(() => {
    if (messages.length === 0) {
      signupNudgedRef.current = false
      ratingNudgedRef.current = false
      setPendingQuote(null)
    }
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
  // First-run intake is for anonymous users only: a signed-in user already has a saved profile that
  // seeds their plans. It precedes the welcome screen and is fully skippable.
  const showIntake = !auth.user && !profile.intakeDone && !hasMessages
  const showRetry = !isStreaming && messages[messages.length - 1]?.isError
  // The dead air between sending and the first streamed token: research, logistics, compile. While
  // comparing, the variants build in the canvas, so the chat loader steps aside.
  const planning = isStreaming && !messages.some((m) => m.role === 'ai-stream') && !comparing

  // The presence of an itinerary is what splits the view. The canvas follows the latest by default,
  // but an older ItineraryCard can pin its own version back into the canvas.
  let latestItineraryIndex = -1
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].isItinerary) { latestItineraryIndex = i; break }
  }
  // An itinerary, or two variants being compared, splits the view into chat + canvas.
  const split = latestItineraryIndex >= 0 || comparing
  const viewedIndex = messages[viewedItineraryIndex]?.isItinerary ? viewedItineraryIndex : latestItineraryIndex
  const viewedItinerary = latestItineraryIndex >= 0 ? messages[viewedIndex] : null
  const activeVariantData = comparing ? variants[activeVariant] || { content: '', geo: null } : null

  // A fresh plan can be requested as two variants; edits and follow-ups (once a plan exists) never are.
  const handleSend = (text) => sendMessage(text, { compare: compareMode && !split })

  // App-level feedback / bug report from the header, always available.
  const openAppFeedback = () =>
    setFeedbackTarget({
      kind: 'app',
      title: 'Feedback or a problem?',
      placeholder: "What worked, what didn't, or a bug to report (optional)",
    })

  const submitFeedback = async ({ rating, message }) => {
    const target = feedbackTarget
    const ok = await feedback.submit({
      kind: target.kind,
      rating,
      message,
      sessionId: target.kind === 'app' ? null : sessionId,
      context: target.context,
    })
    setFeedbackTarget(null)
    feedback.reset()
    setToast(ok ? 'Thanks for the feedback.' : 'Could not send feedback. Please try again.')
    setTimeout(() => setToast(null), 4000)
  }

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

  const inputBar = (
    <InputBar
      onSend={handleSend}
      isStreaming={isStreaming}
      onStop={stopStreaming}
      quote={pendingQuote}
      onClearQuote={() => setPendingQuote(null)}
      showCompare={!split}
      compareMode={compareMode}
      onToggleCompare={() => setCompareMode((on) => !on)}
    />
  )

  return (
    <div className={`app ${split ? 'app--split' : ''}`}>
      <Header
        user={auth.user}
        onSignIn={() => setAuthOpen(true)}
        onSignOut={handleSignOut}
        onToggleTrips={auth.user ? () => { setSidebarOpen((o) => !o); trips.refresh() } : null}
        onSettings={auth.user ? () => setSettingsOpen(true) : null}
        onFeedback={openAppFeedback}
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
        showIntake ? (
          <Intake onComplete={profile.saveIntake} onSkip={profile.skipIntake} />
        ) : (
          <Welcome onPrompt={handleSend} />
        )
      ) : split ? (
        <div className="workspace">
          <div className={`workspace__chat ${mobileView === 'chat' ? 'is-active' : ''}`}>
            {chatScroll}
            {inputBar}
          </div>
          <div className={`workspace__canvas ${mobileView === 'canvas' ? 'is-active' : ''}`}>
            {comparing ? (
              <Canvas
                itinerary={{ content: activeVariantData.content }}
                geo={activeVariantData.geo}
                isStreaming={isStreaming}
                variant={activeVariant}
                onSelectVariant={selectVariant}
                onKeepVariant={keepVariant}
              />
            ) : (
              <Canvas
                itinerary={viewedItinerary}
                geo={itineraryGeo}
                onRegenerate={regenerate}
                isStreaming={isStreaming}
                onShare={() => share.share({ itinerary_text: viewedItinerary?.content, geo: itineraryGeo })}
                shareStatus={share.status}
                onUnshare={share.unshare}
                isShared={share.isShared}
                onAddToChat={(text) => { setPendingQuote(text); setMobileView('chat') }}
                onRate={() => setFeedbackTarget({ kind: 'plan', title: 'How was this plan?', placeholder: 'Anything you liked or would change? (optional)' })}
              />
            )}
          </div>
        </div>
      ) : (
        chatScroll
      )}

      {/* In the split, the input lives inside the chat column; everywhere else it sits at the bottom. */}
      {!split && inputBar}

      {feedbackTarget && (
        <FeedbackBubble title={feedbackTarget.title} onClose={() => { setFeedbackTarget(null); feedback.reset() }}>
          <FeedbackForm
            busy={feedback.status === 'sending'}
            placeholder={feedbackTarget.placeholder}
            onSubmit={submitFeedback}
          />
        </FeedbackBubble>
      )}

      {!consent.decided && <ConsentBanner onAccept={consent.accept} onDecline={consent.decline} />}
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
      {signupPrompt && !auth.user && (
        <SignupPrompt
          onSignUp={() => { setSignupPrompt(false); setAuthOpen(true) }}
          onDismiss={() => setSignupPrompt(false)}
        />
      )}
      {authOpen && <AuthModal auth={auth} onClose={() => setAuthOpen(false)} />}
      {settingsOpen && auth.user && <AccountSettings auth={auth} onClose={() => setSettingsOpen(false)} />}
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
