import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SharedItinerary from '../components/SharedItinerary'

// Map is lazy and pulls in Leaflet, so stub it; its own behavior is covered by Map.test.
vi.mock('../components/Map', () => ({
  default: ({ geo }) => <div data-testid="canvas-map">{geo ? 'map' : 'no-geo'}</div>,
}))

const SNAPSHOT = {
  id: 'abc123',
  title: 'Trip to Rome',
  itinerary_text: '# Trip to Rome\n## Day 1',
  geo: { hotel: null, days: [{ day: 1, title: 'Ancient core', places: [] }] },
  created_at: '2026-06-20T00:00:00+00:00',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

test('fetches the snapshot by id and renders it read-only', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => SNAPSHOT })))

  render(<SharedItinerary id="abc123" />)

  expect(await screen.findByText('Ancient core')).toBeInTheDocument()
  expect(document.querySelector('.canvas__title')).toHaveTextContent('Trip to Rome')
  // read-only: no authoring actions
  expect(screen.queryByRole('button', { name: /regenerate/i })).toBeNull()
  expect(screen.queryByRole('button', { name: /^share$/i })).toBeNull()
})

test('offers a copy-link action for the current page url', async () => {
  const writeText = vi.fn().mockResolvedValue()
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => SNAPSHOT })))

  render(<SharedItinerary id="abc123" />)
  await screen.findByText('Ancient core')

  fireEvent.click(screen.getByRole('button', { name: /copy link/i }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(window.location.href))
})

test('shows a not-found message when the snapshot is missing', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })))

  render(<SharedItinerary id="missing" />)
  expect(await screen.findByText(/not found/i)).toBeInTheDocument()
})
