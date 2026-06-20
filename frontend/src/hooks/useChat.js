import { useState, useRef, useCallback, useEffect } from 'react'
import { stageFor } from '../planningStages'

// Map stored {user, model} history into UI message shape, marking itinerary messages so they
// render as markdown.
export function toUiMessages(history) {
  let seenItinerary = false
  return (history || []).map((m) => {
    if (m.role === 'user') return { role: 'user', content: m.content }
    const isItinerary = m.content.includes('## Day') || m.content.includes('Trip to')
    const msg = { role: 'ai', content: m.content, isItinerary }
    // A later itinerary in the same history is a revision of an earlier one, so mark it updated.
    if (isItinerary && seenItinerary) msg.isUpdated = true
    if (isItinerary) seenItinerary = true
    return msg
  })
}

export function useChat({ onItineraryDelivered } = {}) {
  // Keep the latest callback in a ref so sendMessage's deps stay stable.
  const onItineraryRef = useRef(onItineraryDelivered)
  onItineraryRef.current = onItineraryDelivered

  const [messages, setMessages] = useState([])
  const [statuses, setStatuses] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [itineraryGeo, setItineraryGeo] = useState(null)
  const [planningStage, setPlanningStage] = useState(null)
  const abortRef = useRef(null)
  const sessionIdRef = useRef(localStorage.getItem('atlas_session_id') || null)
  const lastTextRef = useRef('')

  // A persisted session id with an empty visible chat is a stale carry-over from a previous page
  // load. Reusing it would make a brand-new planning request land as an edit of the old plan, so
  // start a fresh session. An authed user can still reopen a saved trip from the sidebar.
  useEffect(() => {
    if (sessionIdRef.current && messages.length === 0) {
      sessionIdRef.current = null
      localStorage.removeItem('atlas_session_id')
    }
  }, [])

  const sendMessage = useCallback(async (text, opts = {}) => {
    if (!text.trim() || isStreaming) return

    lastTextRef.current = text
    if (opts.isRetry) {
      // drop the trailing error message, then re-send without a duplicate user bubble
      setMessages(prev => (prev[prev.length - 1]?.isError ? prev.slice(0, -1) : prev))
    } else {
      setMessages(prev => [...prev, { role: 'user', content: text }])
    }
    setStatuses([])
    setIsStreaming(true)

    let aiContent = ''
    let isItinerary = false
    let isEdit = false
    let editSummary = ''
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
        if (res.status === 401) window.dispatchEvent(new Event('atlas-unauthorized'))
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
              // Themed loader caption for this stage, one line picked at random from its pool.
              const stage = stageFor(event.node)
              setPlanningStage({ variant: stage.variant, line: stage.lines[Math.floor(Math.random() * stage.lines.length)] })
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
              isEdit = event.is_edit || false
              editSummary = event.edit_summary || ''
              // A fresh plan refreshes the map; an edit re-geocodes nothing, so keep the prior map.
              if (isItinerary && !isEdit) setItineraryGeo(event.geo || { hotel: null, days: [] })
              currentStatuses = currentStatuses.map(s => ({ ...s, state: 'done' }))
              setStatuses([...currentStatuses])
              break
            }

            case 'error': {
              setMessages(prev => [
                ...prev.filter(m => m.role !== 'ai-stream'),
                { role: 'ai', content: event.content || 'Something went wrong.', isError: true },
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
          return [...filtered, { role: 'ai', content: aiContent, isItinerary, isUpdated: isEdit, updatedSummary: editSummary }]
        })
      }

      if (isItinerary) onItineraryRef.current?.({ isEdit })
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
          { role: 'ai', content: err.message || 'Connection lost. Please try again.', isError: true },
        ])
      }
    } finally {
      setIsStreaming(false)
      setStatuses([])  // clear progress pills once the turn ends (no lingering "thinking")
      setPlanningStage(null)
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
    setItineraryGeo(null)
    setPlanningStage(null)
  }, [])

  // Render a saved trip's itinerary as a read-only view (used by the trips sidebar).
  const showItinerary = useCallback((text, geo) => {
    setMessages([{ role: 'ai', content: text, isItinerary: true }])
    setStatuses([])
    setItineraryGeo(geo || null)
  }, [])

  // Resume a saved conversation: adopt its session id and hydrate the messages.
  const loadSession = useCallback((sessionId, history, geo) => {
    sessionIdRef.current = sessionId
    localStorage.setItem('atlas_session_id', sessionId)
    setMessages(toUiMessages(history))
    setStatuses([])
    setItineraryGeo(geo || null)
  }, [])

  const retry = useCallback(() => {
    if (lastTextRef.current) return sendMessage(lastTextRef.current, { isRetry: true })
  }, [sendMessage])

  // Regenerate sends a fresh-plan instruction rather than replaying the original prompt. A plan is
  // often built over several interview turns, so there is no single prompt to replay, and the
  // pipeline keys on these words: a post-plan message matching them re-runs the full research and
  // compile pass (fresh map/geo, is_edit stays false) instead of editing the prior plan in place.
  const regenerate = useCallback(() => {
    return sendMessage('Regenerate this plan from scratch with fresh ideas.')
  }, [sendMessage])

  return { messages, statuses, isStreaming, itineraryGeo, planningStage, sendMessage, stopStreaming, newChat, showItinerary, loadSession, retry, regenerate }
}
