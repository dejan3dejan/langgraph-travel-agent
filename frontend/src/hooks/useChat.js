import { useState, useRef, useCallback } from 'react'

export function useChat() {
  const [messages, setMessages] = useState([])
  const [statuses, setStatuses] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef(null)
  const historyRef = useRef([])

  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || isStreaming) return

    const userMsg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setStatuses([])
    setIsStreaming(true)

    let aiContent = ''
    let isItinerary = false
    let currentStatuses = []
    let lastActiveNode = null

    try {
      abortRef.current = new AbortController()

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          history: historyRef.current,
        }),
        signal: abortRef.current.signal,
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          let event
          try { event = JSON.parse(raw) } catch { continue }

          switch (event.type) {
            case 'status': {
              if (lastActiveNode) {
                currentStatuses = currentStatuses.map(s =>
                  s.node === lastActiveNode ? { ...s, state: 'done' } : s
                )
              }
              lastActiveNode = event.node
              currentStatuses = [
                ...currentStatuses.filter(s => s.node !== event.node),
                { node: event.node, label: event.content, state: 'active' },
              ]
              setStatuses([...currentStatuses])
              break
            }

            case 'token': {
              aiContent += event.content
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last?.role === 'ai-stream') {
                  return [...prev.slice(0, -1), { role: 'ai-stream', content: aiContent }]
                }
                return [...prev, { role: 'ai-stream', content: aiContent }]
              })
              break
            }

            case 'reset': {
              aiContent = ''
              setMessages(prev => prev.filter(m => m.role !== 'ai-stream'))
              break
            }

            case 'end': {
              isItinerary = event.is_itinerary || false
              currentStatuses = currentStatuses.map(s => ({ ...s, state: 'done' }))
              setStatuses([...currentStatuses])
              break
            }

            case 'error': {
              setMessages(prev => [
                ...prev.filter(m => m.role !== 'ai-stream'),
                { role: 'ai', content: event.content || 'Something went wrong.' },
              ])
              break
            }
          }
        }
      }

      // finalize streaming message
      if (aiContent) {
        setMessages(prev => {
          const filtered = prev.filter(m => m.role !== 'ai-stream')
          return [...filtered, { role: 'ai', content: aiContent, isItinerary }]
        })
      }

      historyRef.current = [
        ...historyRef.current,
        { role: 'user', content: text },
        { role: 'model', content: aiContent },
      ]
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages(prev => [
          ...prev,
          { role: 'ai', content: 'Connection lost. Please try again.' },
        ])
      }
    } finally {
      setIsStreaming(false)
      setStatuses([])  // clear progress pills once the turn ends (no lingering "thinking")
      abortRef.current = null
    }
  }, [isStreaming])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return { messages, statuses, isStreaming, sendMessage, stopStreaming }
}
