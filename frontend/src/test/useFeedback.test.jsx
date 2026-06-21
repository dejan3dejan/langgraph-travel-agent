import { renderHook, act } from '@testing-library/react'
import { useFeedback } from '../hooks/useFeedback'

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

test('submit posts the feedback payload and reports success', async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) }))
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useFeedback())
  let ok
  await act(async () => {
    ok = await result.current.submit({ kind: 'plan', rating: 4, message: 'great', sessionId: 'sess-1' })
  })

  expect(ok).toBe(true)
  expect(result.current.status).toBe('sent')
  const [url, opts] = fetchMock.mock.calls[0]
  expect(url).toContain('/api/feedback')
  expect(JSON.parse(opts.body)).toMatchObject({ kind: 'plan', rating: 4, message: 'great', session_id: 'sess-1' })
})

test('submit reports failure on a non-ok response without throwing', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })))
  const { result } = renderHook(() => useFeedback())
  let ok
  await act(async () => {
    ok = await result.current.submit({ kind: 'app', message: 'bug' })
  })
  expect(ok).toBe(false)
  expect(result.current.status).toBe('error')
})

test('submit sends an auth header when a token is stored', async () => {
  localStorage.setItem('atlas_token', 'tok-9')
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) }))
  vi.stubGlobal('fetch', fetchMock)
  const { result } = renderHook(() => useFeedback())
  await act(async () => {
    await result.current.submit({ kind: 'app', rating: 5 })
  })
  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tok-9')
})
