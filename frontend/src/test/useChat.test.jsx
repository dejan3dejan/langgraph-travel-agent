import { renderHook, act, waitFor } from '@testing-library/react'
import { useChat, toUiMessages } from '../hooks/useChat'

function encode(s) {
  return new TextEncoder().encode(s)
}

// A fetch mock whose reader yields the given SSE lines, then signals done.
function streamingFetch(lines) {
  return vi.fn(async () => ({
    ok: true,
    status: 200,
    body: {
      getReader: () => {
        let i = 0
        return {
          read: () =>
            i < lines.length
              ? Promise.resolve({ done: false, value: encode(lines[i++]) })
              : Promise.resolve({ done: true }),
        }
      },
    },
  }))
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('D3: a non-ok response surfaces the real error instead of failing silently', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: false,
      status: 429,
      json: async () => ({ detail: 'Too many requests' }),
    })),
  )

  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('hi')
  })

  await waitFor(() => {
    const ai = result.current.messages.find((m) => m.role === 'ai')
    expect(ai?.content).toContain('Too many requests')
  })
  expect(result.current.isStreaming).toBe(false)
})

test('D4: stopping mid-stream finalizes the partial, leaving no ghost', async () => {
  const abortError = Object.assign(new Error('Aborted'), { name: 'AbortError' })
  const chunk = 'data: {"type":"token","content":"Planning your trip"}\n\n'

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, options) => ({
      ok: true,
      status: 200,
      body: {
        getReader: () => {
          let i = 0
          return {
            read: () =>
              new Promise((resolve, reject) => {
                if (i === 0) {
                  i++
                  resolve({ done: false, value: encode(chunk) })
                } else if (options.signal.aborted) {
                  reject(abortError)
                } else {
                  options.signal.addEventListener('abort', () => reject(abortError))
                }
              }),
          }
        },
      },
    })),
  )

  const { result } = renderHook(() => useChat())
  act(() => {
    result.current.sendMessage('hi')
  })

  await waitFor(() => {
    expect(result.current.messages.some((m) => m.role === 'ai-stream')).toBe(true)
  })

  act(() => {
    result.current.stopStreaming()
  })

  await waitFor(() => {
    expect(result.current.messages.some((m) => m.role === 'ai-stream')).toBe(false)
    expect(
      result.current.messages.some((m) => m.role === 'ai' && m.content.includes('Planning your trip')),
    ).toBe(true)
  })
})

test('B3: fires onItineraryDelivered when a plan is delivered', async () => {
  const cb = vi.fn()
  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"# Trip to Rome"}\n\n',
      'data: {"type":"end","is_itinerary":true}\n\n',
    ]),
  )
  const { result } = renderHook(() => useChat({ onItineraryDelivered: cb }))
  await act(async () => {
    await result.current.sendMessage('plan rome')
  })
  await waitFor(() => expect(cb).toHaveBeenCalledTimes(1))
})

test('B3: does not fire onItineraryDelivered for a plain reply', async () => {
  const cb = vi.fn()
  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"How many days?"}\n\n',
      'data: {"type":"end","is_itinerary":false}\n\n',
    ]),
  )
  const { result } = renderHook(() => useChat({ onItineraryDelivered: cb }))
  await act(async () => {
    await result.current.sendMessage('hi')
  })
  expect(cb).not.toHaveBeenCalled()
})

test('happy path: a normal stream stores the session id and finalizes the message', async () => {
  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"session","session_id":"sess-123"}\n\n',
      'data: {"type":"token","content":"Hi there"}\n\n',
      'data: {"type":"end","is_itinerary":false}\n\n',
    ]),
  )

  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('hi')
  })

  await waitFor(() => {
    expect(result.current.messages.some((m) => m.role === 'ai' && m.content === 'Hi there')).toBe(true)
  })
  expect(localStorage.getItem('atlas_session_id')).toBe('sess-123')
})

test('D3.2: retry re-sends the last message, drops the error, no duplicate user bubble', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ detail: 'boom' }) })),
  )
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('plan rome')
  })
  await waitFor(() => expect(result.current.messages.some((m) => m.isError)).toBe(true))

  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"# Trip to Rome"}\n\n',
      'data: {"type":"end","is_itinerary":true}\n\n',
    ]),
  )
  await act(async () => {
    await result.current.retry()
  })

  await waitFor(() => {
    expect(result.current.messages.some((m) => m.isError)).toBe(false)
    expect(result.current.messages.some((m) => m.role === 'ai' && m.content.includes('Trip to Rome'))).toBe(true)
  })
  expect(result.current.messages.filter((m) => m.role === 'user').length).toBe(1)
})

test('A1: toUiMessages maps roles and marks itineraries', () => {
  expect(
    toUiMessages([
      { role: 'user', content: 'plan rome' },
      { role: 'model', content: '# Trip to Rome\n## Day 1' },
      { role: 'model', content: 'How many days?' },
    ]),
  ).toEqual([
    { role: 'user', content: 'plan rome' },
    { role: 'ai', content: '# Trip to Rome\n## Day 1', isItinerary: true },
    { role: 'ai', content: 'How many days?', isItinerary: false },
  ])
})

test('A1: loadSession hydrates messages and adopts the session', () => {
  const { result } = renderHook(() => useChat())
  act(() => {
    result.current.loadSession('sess-9', [{ role: 'user', content: 'hi' }])
  })
  expect(result.current.messages).toEqual([{ role: 'user', content: 'hi' }])
  expect(localStorage.getItem('atlas_session_id')).toBe('sess-9')
})

test('C1: an edit end marks the finalized itinerary as updated', async () => {
  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"# Trip to Rome"}\n\n',
      'data: {"type":"end","is_itinerary":true,"is_edit":true}\n\n',
    ]),
  )
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('swap the Tuesday restaurant')
  })
  await waitFor(() => {
    const ai = result.current.messages.find((m) => m.role === 'ai' && m.isItinerary)
    expect(ai?.isUpdated).toBe(true)
  })
})

test('C1: onItineraryDelivered receives isEdit', async () => {
  const cb = vi.fn()
  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"# Trip to Rome"}\n\n',
      'data: {"type":"end","is_itinerary":true,"is_edit":true}\n\n',
    ]),
  )
  const { result } = renderHook(() => useChat({ onItineraryDelivered: cb }))
  await act(async () => {
    await result.current.sendMessage('swap the Tuesday restaurant')
  })
  await waitFor(() => expect(cb).toHaveBeenCalledWith({ isEdit: true }))
})

test('C1: toUiMessages marks a later itinerary as updated', () => {
  const out = toUiMessages([
    { role: 'user', content: 'plan rome' },
    { role: 'model', content: '# Trip to Rome\n## Day 1' },
    { role: 'user', content: 'swap the restaurant' },
    { role: 'model', content: '# Trip to Rome\n## Day 1 revised' },
  ])
  expect(out[1].isItinerary).toBe(true)
  expect(out[1].isUpdated).toBeUndefined()
  expect(out[3].isItinerary).toBe(true)
  expect(out[3].isUpdated).toBe(true)
})

test('C1: an edit carries the change summary onto the finalized message', async () => {
  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"# Trip to Rome"}\n\n',
      'data: {"type":"end","is_itinerary":true,"is_edit":true,"edit_summary":"swap the Tuesday restaurant"}\n\n',
    ]),
  )
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('swap the Tuesday restaurant')
  })
  await waitFor(() => {
    const ai = result.current.messages.find((m) => m.role === 'ai' && m.isItinerary)
    expect(ai?.updatedSummary).toBe('swap the Tuesday restaurant')
  })
})

const GEO = {
  hotel: null,
  days: [{ day: 1, zone: 'near', label: 'Walkable', places: [{ name: 'X', lat: 1, lon: 2, kind: 'activity' }] }],
}

function planThenEnd(extra) {
  return streamingFetch([
    'data: {"type":"token","content":"# Trip to Rome"}\n\n',
    `data: ${JSON.stringify({ type: 'end', is_itinerary: true, ...extra })}\n\n`,
  ])
}

test('C2: an itinerary end carrying geo exposes it for the map', async () => {
  vi.stubGlobal('fetch', planThenEnd({ geo: GEO }))
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('plan rome')
  })
  await waitFor(() => expect(result.current.itineraryGeo).toEqual(GEO))
})

test('C2: an edit end keeps the existing map (no fresh coords)', async () => {
  vi.stubGlobal('fetch', planThenEnd({ geo: GEO }))
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('plan rome')
  })
  await waitFor(() => expect(result.current.itineraryGeo).toEqual(GEO))

  vi.stubGlobal('fetch', planThenEnd({ is_edit: true, geo: null }))
  await act(async () => {
    await result.current.sendMessage('swap the restaurant')
  })
  await waitFor(() => expect(result.current.messages.some((m) => m.isUpdated)).toBe(true))
  expect(result.current.itineraryGeo).toEqual(GEO)
})

test('C2: a plain follow-up reply does not wipe the map', async () => {
  vi.stubGlobal('fetch', planThenEnd({ geo: GEO }))
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('plan rome')
  })
  await waitFor(() => expect(result.current.itineraryGeo).toEqual(GEO))

  vi.stubGlobal(
    'fetch',
    streamingFetch([
      'data: {"type":"token","content":"Prices are estimates."}\n\n',
      'data: {"type":"end","is_itinerary":false}\n\n',
    ]),
  )
  await act(async () => {
    await result.current.sendMessage('how accurate are prices?')
  })
  await waitFor(() => expect(result.current.messages.some((m) => m.content.includes('estimates'))).toBe(true))
  expect(result.current.itineraryGeo).toEqual(GEO)
})

test('C2: newChat clears the map', async () => {
  vi.stubGlobal('fetch', planThenEnd({ geo: GEO }))
  const { result } = renderHook(() => useChat())
  await act(async () => {
    await result.current.sendMessage('plan rome')
  })
  await waitFor(() => expect(result.current.itineraryGeo).toEqual(GEO))
  act(() => result.current.newChat())
  expect(result.current.itineraryGeo).toBeNull()
})
