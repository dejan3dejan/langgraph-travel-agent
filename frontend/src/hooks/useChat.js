import { useState, useRef, useCallback, useEffect } from 'react'
import { stageFor } from '../planningStages'
import { apiUrl } from '../api'
import { readAnonPrefs } from './useProfile'

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
  // Compare mode: the two streamed itinerary variants and which one the canvas is showing. Null when
  // not comparing. Mirrored in a ref so keepVariant reads the latest without a stale closure.
  const [variants, setVariants] = useState(null)
  const [activeVariant, setActiveVariant] = useState('A')
  const variantsRef = useRef(null)
  const comparingRef = useRef(false)
  const variantBufRef = useRef({ A: '', B: '' })
  const abortRef = useRef(null)
  const sessionIdRef = useRef(localStorage.getItem('atlas_session_id') || null)
  const lastTextRef = useRef('')

  // Compare-state writers keep the ref and the rendered state in lockstep.
  const resetCompare = () => {
    comparingRef.current = false
    variantsRef.current = null
    variantBufRef.current = { A: '', B: '' }
    setVariants(null)
    setActiveVariant('A')
  }

  const enterCompare = (variant) => {
    comparingRef.current = true
    variantBufRef.current = { A: '', B: '' }
    variantsRef.current = { A: { content: '', geo: null }, B: { content: '', geo: null } }
    setVariants(variantsRef.current)
    setActiveVariant(variant)
  }

  const writeVariant = (variant, patch) => {
    const cur = variantsRef.current || { A: { content: '', geo: null }, B: { content: '', geo: null } }
    const next = { ...cur, [variant]: { ...cur[variant], ...patch } }
    variantsRef.current = next
    setVariants(next)
  }

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
    resetCompare()
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

      const body = {
        message: text,
        session_id: sessionIdRef.current,
        compare: !!opts.compare,
      }
      // Anonymous users have no saved profile, so carry their intake prefs with the request to seed
      // the plan. Authed users are seeded server-side from their profile, so this is omitted.
      if (!token) {
        const prefs = readAnonPrefs()
        if (prefs) body.client_prefs = prefs
      }

      const res = await fetch(apiUrl('/api/chat/stream'), {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
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
              // Compare mode engages only once a variant is actually being compiled (an interview
              // question never reaches the compiler, so it stays a normal reply). Variant B's compiler
              // stage just moves the canvas focus to B.
              if (event.variant && event.node === 'compiler') {
                if (!comparingRef.current) enterCompare(event.variant)
                else setActiveVariant(event.variant)
              }
              break
            }

            case 'token': {
              if (comparingRef.current && event.variant) {
                const v = event.variant
                variantBufRef.current[v] += event.content
                writeVariant(v, { content: variantBufRef.current[v] })
                break
              }
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
              if (comparingRef.current && event.variant) {
                const v = event.variant
                variantBufRef.current[v] = ''
                writeVariant(v, { content: '' })
                break
              }
              aiContent = ''
              setMessages(prev => prev.filter(m => m.role !== 'ai-stream'))
              break
            }

            case 'end': {
              currentStatuses = currentStatuses.map(s => ({ ...s, state: 'done' }))
              setStatuses([...currentStatuses])

              if (comparingRef.current && event.variant) {
                const v = event.variant
                writeVariant(v, { geo: event.geo ?? null })
                if (event.is_final && v === 'B') {
                  // Both variants are ready; keep the compare view and commit nothing until the user
                  // chooses. Default the selection back to A, the primary recommendation.
                  setActiveVariant('A')
                } else if (event.is_final) {
                  // Variant A finalized with no B following (an edit, or a stray compiled reply): fall
                  // back to the single-itinerary flow using A's text.
                  isItinerary = event.is_itinerary || false
                  isEdit = event.is_edit || false
                  editSummary = event.edit_summary || ''
                  if (isItinerary && !isEdit) setItineraryGeo(event.geo || { hotel: null, days: [] })
                  aiContent = variantBufRef.current.A
                  resetCompare()
                }
                break
              }

              isItinerary = event.is_itinerary || false
              isEdit = event.is_edit || false
              editSummary = event.edit_summary || ''
              // A fresh plan refreshes the map; an edit re-geocodes nothing, so keep the prior map.
              if (isItinerary && !isEdit) setItineraryGeo(event.geo || { hotel: null, days: [] })
              break
            }

            case 'error': {
              if (comparingRef.current) resetCompare()
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
      // A stopped or failed compare leaves no half-built variants behind.
      if (comparingRef.current) resetCompare()
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
    resetCompare()
  }, [])

  // Compare mode: pick which variant the canvas shows.
  const selectVariant = useCallback((variant) => setActiveVariant(variant), [])

  // Keep the chosen variant: tell the backend to commit it, then collapse the compare view into the
  // normal single-itinerary flow (the kept plan becomes an ordinary itinerary message + map).
  const keepVariant = useCallback(async (variant) => {
    const chosen = variantsRef.current?.[variant]
    if (!chosen) return

    const headers = { 'Content-Type': 'application/json' }
    const token = localStorage.getItem('atlas_token')
    if (token) headers.Authorization = `Bearer ${token}`

    let res
    try {
      res = await fetch(apiUrl('/api/chat/keep-variant'), {
        method: 'POST',
        headers,
        body: JSON.stringify({ session_id: sessionIdRef.current, variant }),
      })
    } catch {
      res = null
    }
    if (!res || !res.ok) {
      if (res?.status === 401) window.dispatchEvent(new Event('atlas-unauthorized'))
      setMessages(prev => [...prev, { role: 'ai', content: 'Could not save your choice. Please try again.', isError: true }])
      return
    }

    setMessages(prev => [...prev, { role: 'ai', content: chosen.content, isItinerary: true }])
    setItineraryGeo(chosen.geo || { hotel: null, days: [] })
    resetCompare()
    onItineraryRef.current?.({ isEdit: false, fromCompare: true, chosen: variant })
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

  return { messages, statuses, isStreaming, itineraryGeo, planningStage, variants, activeVariant, selectVariant, keepVariant, sessionId: sessionIdRef.current, sendMessage, stopStreaming, newChat, showItinerary, loadSession, retry, regenerate }
}
