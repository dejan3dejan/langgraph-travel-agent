import { renderHook, act, waitFor } from '@testing-library/react'
import { useShare } from '../hooks/useShare'

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue() },
    configurable: true,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('posts the itinerary snapshot and copies the built link to the clipboard', async () => {
  const fetch = vi.fn(async () => ({ ok: true, status: 201, json: async () => ({ id: 'abc123' }) }))
  vi.stubGlobal('fetch', fetch)

  const { result } = renderHook(() => useShare())
  let url
  await act(async () => {
    url = await result.current.share({ itinerary_text: '# Trip to Rome', geo: { days: [] } })
  })

  const [path, opts] = fetch.mock.calls[0]
  expect(path).toBe('/api/share')
  expect(opts.method).toBe('POST')
  expect(JSON.parse(opts.body)).toEqual({ itinerary_text: '# Trip to Rome', geo: { days: [] } })

  expect(url).toBe(`${window.location.origin}/?share=abc123`)
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`${window.location.origin}/?share=abc123`)
  await waitFor(() => expect(result.current.status).toBe('copied'))
})

test('surfaces an error status when the request fails instead of pretending it shared', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })))

  const { result } = renderHook(() => useShare())
  await act(async () => {
    await result.current.share({ itinerary_text: '# Trip', geo: null })
  })

  await waitFor(() => expect(result.current.status).toBe('error'))
  expect(navigator.clipboard.writeText).not.toHaveBeenCalled()
})
