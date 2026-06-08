import { useRef, useEffect, useState } from 'react'
import './App.css'
import { useChat } from './hooks/useChat'
import { useAuth } from './hooks/useAuth'
import Header from './components/Header'
import Welcome from './components/Welcome'
import Message from './components/Message'
import StatusBar from './components/StatusBar'
import InputBar from './components/InputBar'
import AuthModal from './components/AuthModal'

export default function App() {
  const { messages, statuses, isStreaming, sendMessage, stopStreaming, newChat } = useChat()
  const auth = useAuth()
  const [authOpen, setAuthOpen] = useState(false)
  const chatEndRef = useRef(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, statuses])

  const hasMessages = messages.length > 0

  // Sign out also resets the chat so the next person does not inherit the session.
  const handleSignOut = () => {
    auth.logout()
    newChat()
  }

  return (
    <>
      <Header user={auth.user} onSignIn={() => setAuthOpen(true)} onSignOut={handleSignOut} />

      {hasMessages && (
        <div className="toolbar">
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

      {authOpen && <AuthModal auth={auth} onClose={() => setAuthOpen(false)} />}
    </>
  )
}
