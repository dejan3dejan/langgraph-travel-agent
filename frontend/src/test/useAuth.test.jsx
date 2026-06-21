import { renderHook, act, waitFor } from '@testing-library/react'
import { useAuth } from '../hooks/useAuth'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('B4.1: a stale token is cleared on load', async () => {
  localStorage.setItem('atlas_token', 'stale')
  localStorage.setItem('atlas_user', JSON.stringify({ username: 'bob' }))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401 })))

  const { result } = renderHook(() => useAuth())

  await waitFor(() => expect(result.current.user).toBeNull())
  expect(localStorage.getItem('atlas_token')).toBeNull()
})

test('B4.1: a valid token keeps the user on load', async () => {
  localStorage.setItem('atlas_token', 'good')
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => ({ id: '1', username: 'bob', email: 'b@x.com' }) })),
  )

  const { result } = renderHook(() => useAuth())

  await waitFor(() => expect(result.current.user?.username).toBe('bob'))
})

test('register sends anonymous intake prefs and clears them on success', async () => {
  localStorage.setItem('atlas_prefs', JSON.stringify({ budget: 'High', dietary: ['vegan'] }))
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ access_token: 't', user: { id: '1', username: 'bob' } }),
  }))
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useAuth())
  await act(async () => {
    await result.current.register('b@x.com', 'bob', 'secret1')
  })

  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body.preferences).toEqual({ budget: 'High', dietary: ['vegan'] })
  expect(localStorage.getItem('atlas_prefs')).toBeNull()
})

test('login does not attach intake prefs', async () => {
  localStorage.setItem('atlas_prefs', JSON.stringify({ budget: 'High' }))
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ access_token: 't', user: { id: '1', username: 'bob' } }),
  }))
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useAuth())
  await act(async () => {
    await result.current.login('b@x.com', 'secret1')
  })

  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body.preferences).toBeUndefined()
  // a login leaves the local prefs in place; the account's own saved prefs win server-side
  expect(localStorage.getItem('atlas_prefs')).not.toBeNull()
})

test('B4.2: an unauthorized event logs the user out', async () => {
  localStorage.setItem('atlas_token', 'good')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ username: 'bob' }) })))

  const { result } = renderHook(() => useAuth())
  await waitFor(() => expect(result.current.user?.username).toBe('bob'))

  act(() => {
    window.dispatchEvent(new Event('atlas-unauthorized'))
  })

  await waitFor(() => expect(result.current.user).toBeNull())
})
