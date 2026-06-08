import { useState, useRef, useCallback } from 'react'

export function useChat() {
  const [messages, setMessages] = useState([])
  const [statuses, setStatuses] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef(null)
  const sessionIdRef = useRef(localStorage.getItem('atlas_session_id') || null)

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

      const headers = { 'Content-Type': 'application/json' }
      const token = localStorage.getItem('atlas_token')
      if (token) headers.Authorization = `Bearer ${token}`

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: text,
          session_id: sessionIdRef.current,
        }),
        signal: abortRef.current.signal,
      })

      if (!res.ok) {
        let detail = `Request failed (${res.status})`
        try {
          const body = await res.json()
          if (body.detail) detail = body.detail
        } catch {
          // non-JSON error body; keep the status-code fallback
        }
        throw new Error(detail)
      }

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
            case 'session': {
              sessionIdRef.current = event.session_id
              localStorage.setItem('atlas_session_id', event.session_id)
              break
            }

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
    } catch (err) {
      if (err.name === 'AbortError') {
        // Stopped mid-stream: keep whatever was generated as a final message so there is no
        // frozen ai-stream bubble with a blinking cursor.
        setMessages(prev => {
          const kept = prev.filter(m => m.role !== 'ai-stream')
          return aiContent ? [...kept, { role: 'ai', content: aiContent }] : kept
        })
      } else {
        setMessages(prev => [
          ...prev.filter(m => m.role !== 'ai-stream'),
          { role: 'ai', content: err.message || 'Connection lost. Please try again.' },
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

  const newChat = useCallback(() => {
    sessionIdRef.current = null
    localStorage.removeItem('atlas_session_id')
    setMessages([])
    setStatuses([])
  }, [])

  // Render a saved trip's itinerary as a read-only view (used by the trips sidebar).
  const showItinerary = useCallback((text) => {
    setMessages([{ role: 'ai', content: text, isItinerary: true }])
    setStatuses([])
  }, [])

  return { messages, statuses, isStreaming, sendMessage, stopStreaming, newChat, showItinerary }
}
