import { renderHook, act, waitFor } from '@testing-library/react'
import { useChat } from '../hooks/useChat'

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
