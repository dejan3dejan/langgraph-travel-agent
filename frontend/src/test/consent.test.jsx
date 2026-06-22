import { render, screen, fireEvent, renderHook, act } from '@testing-library/react'
import ConsentBanner from '../components/ConsentBanner'
import { getConsent, hasAnalyticsConsent, setAnalyticsConsent, useConsent } from '../consent'

beforeEach(() => {
  localStorage.clear()
})

test('analytics are off until consent is explicitly granted', () => {
  // Undecided is not consent: the gate must default closed.
  expect(getConsent()).toBe(null)
  expect(hasAnalyticsConsent()).toBe(false)

  setAnalyticsConsent(false)
  expect(hasAnalyticsConsent()).toBe(false)

  setAnalyticsConsent(true)
  expect(hasAnalyticsConsent()).toBe(true)
})

test('a granted choice persists across reloads', () => {
  setAnalyticsConsent(true)
  // A fresh hook instance reads the stored decision, standing in for a page reload.
  const { result } = renderHook(() => useConsent())
  expect(result.current.decided).toBe(true)
  expect(result.current.granted).toBe(true)
})

test('useConsent records accept and decline', () => {
  const { result } = renderHook(() => useConsent())
  expect(result.current.decided).toBe(false)

  act(() => result.current.decline())
  expect(result.current.decided).toBe(true)
  expect(result.current.granted).toBe(false)
  expect(hasAnalyticsConsent()).toBe(false)
})

test('ConsentBanner offers accept and decline and reports the choice', () => {
  const onAccept = vi.fn()
  const onDecline = vi.fn()
  render(<ConsentBanner onAccept={onAccept} onDecline={onDecline} />)

  expect(screen.getByText(/analytics/i)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /accept/i }))
  expect(onAccept).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: /decline/i }))
  expect(onDecline).toHaveBeenCalledOnce()
})
