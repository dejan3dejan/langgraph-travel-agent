import { useRef, useEffect } from 'react'
import './App.css'
import { useChat } from './hooks/useChat'
import Header from './components/Header'
import Welcome from './components/Welcome'
import Message from './components/Message'
import StatusBar from './components/StatusBar'
import InputBar from './components/InputBar'

export default function App() {
  const { messages, statuses, isStreaming, sendMessage, stopStreaming } = useChat()
  const chatEndRef = useRef(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, statuses])

  const hasMessages = messages.length > 0

  return (
    <>
      <Header />

      {!hasMessages ? (
        <Welcome onPrompt={sendMessage} />
      ) : (
        <div className="chat-area">
          {messages.map((m, i) => (
            <Message key={i} role={m.role} content={m.content} />
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
    </>
  )
}
