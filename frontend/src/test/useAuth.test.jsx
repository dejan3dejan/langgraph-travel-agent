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
