import { renderHook, act, waitFor } from '@testing-library/react'
import { useProfile, readAnonPrefs } from '../hooks/useProfile'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('anon: intake is not done until completed or skipped', () => {
  const { result } = renderHook(() => useProfile(null))
  expect(result.current.intakeDone).toBe(false)
})

test('anon: saveIntake persists prefs to localStorage and marks intake done', () => {
  const { result } = renderHook(() => useProfile(null))
  act(() => result.current.saveIntake({ budget: 'High', interests: ['food'] }))

  expect(result.current.intakeDone).toBe(true)
  expect(JSON.parse(localStorage.getItem('atlas_prefs'))).toEqual({ budget: 'High', interests: ['food'] })
  expect(localStorage.getItem('atlas_intake_done')).toBe('1')
})

test('anon: skipIntake marks done without storing prefs', () => {
  const { result } = renderHook(() => useProfile(null))
  act(() => result.current.skipIntake())

  expect(result.current.intakeDone).toBe(true)
  expect(localStorage.getItem('atlas_prefs')).toBeNull()
})

test('readAnonPrefs returns stored prefs or null', () => {
  expect(readAnonPrefs()).toBeNull()
  localStorage.setItem('atlas_prefs', JSON.stringify({ budget: 'Low' }))
  expect(readAnonPrefs()).toEqual({ budget: 'Low' })
})

test('authed: loads the saved profile from the API', async () => {
  localStorage.setItem('atlas_token', 'good')
  const profile = {
    default_budget: 'High',
    default_interests: 'food',
    num_travelers: 2,
    age_range: 'adults',
    trip_type: 'romantic',
    start_location: 'Berlin',
    constraints: { hard: ['vegetarian'], soft: [] },
  }
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => profile })))

  const { result } = renderHook(() => useProfile({ id: '1' }))

  await waitFor(() => expect(result.current.profile?.start_location).toBe('Berlin'))
})

test('authed: updateProfile PUTs the partial and updates state', async () => {
  localStorage.setItem('atlas_token', 'good')
  const fetchMock = vi.fn(async (url, opts) => {
    if (opts?.method === 'PUT') {
      return { ok: true, json: async () => ({ ...JSON.parse(opts.body), default_budget: 'Low' }) }
    }
    return { ok: true, json: async () => ({ default_budget: 'High' }) }
  })
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useProfile({ id: '1' }))
  await waitFor(() => expect(result.current.profile?.default_budget).toBe('High'))

  await act(async () => {
    await result.current.updateProfile({ default_budget: 'Low' })
  })
  expect(result.current.profile?.default_budget).toBe('Low')
})
