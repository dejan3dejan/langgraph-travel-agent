import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import App from '../App'

// Map pulls in Leaflet, which can't render in jsdom; stub it to a plain node we can find.
vi.mock('../components/Map', () => ({ default: () => <div data-testid="map" /> }))

function encode(s) { return new TextEncoder().encode(s) }

function readerFor(lines) {
  let i = 0
  return { read: () => i < lines.length
    ? Promise.resolve({ done: false, value: encode(lines[i++]) })
    : Promise.resolve({ done: true }) }
}

function streamingFetch(lines) {
  return vi.fn(async () => ({ ok: true, status: 200, body: { getReader: () => readerFor(lines) } }))
}

// Each call returns the next response, so successive sends stream different itineraries.
function queuedFetch(responses) {
  let call = 0
  return vi.fn(async () => {
    const lines = responses[Math.min(call++, responses.length - 1)]
    return { ok: true, status: 200, body: { getReader: () => readerFor(lines) } }
  })
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('atlas_entered', '1')
})
afterEach(() => vi.unstubAllGlobals())

test('stays full-width chat until a plan lands, then splits with the itinerary in the canvas', async () => {
  const geo = {
    hotel: null,
    days: [{ day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', kind: 'activity' }] }],
  }
  vi.stubGlobal('fetch', streamingFetch([
    'data: {"type":"token","content":"# Trip to Rome"}\n\n',
    `data: ${JSON.stringify({ type: 'end', is_itinerary: true, geo })}\n\n`,
  ]))

  render(<App />)

  // Pre-plan: the Welcome screen, no split workspace yet.
  expect(screen.getByText(/Where shall we/i)).toBeInTheDocument()
  expect(document.querySelector('.workspace')).toBeNull()

  fireEvent.click(screen.getByText('Plan a 3-day trip to Rome on a medium budget'))

  // Once the itinerary is delivered the view splits.
  await waitFor(() => expect(document.querySelector('.workspace')).not.toBeNull())

  // The chat side shows a slim reference, not the full plan.
  expect(screen.getByText('Itinerary ready')).toBeInTheDocument()

  // The full itinerary lives in the canvas, and only there: the chat column has no rendered plan.
  expect(document.querySelector('.workspace__canvas').textContent).toContain('Trip to Rome')
  expect(document.querySelector('.workspace__chat .markdown-body')).toBeNull()
})

test('keeps the input bar on the welcome screen and after the split', async () => {
  const geo = { hotel: null, days: [{ day: 1, title: 'Day one', places: [] }] }
  vi.stubGlobal('fetch', streamingFetch([
    'data: {"type":"token","content":"# Trip to Rome"}\n\n',
    `data: ${JSON.stringify({ type: 'end', is_itinerary: true, geo })}\n\n`,
  ]))

  render(<App />)
  // The empty welcome state still offers somewhere to type.
  expect(screen.getByPlaceholderText(/dream trip/i)).toBeInTheDocument()

  fireEvent.click(screen.getByText('Plan a 3-day trip to Rome on a medium budget'))
  await waitFor(() => expect(document.querySelector('.workspace')).not.toBeNull())

  // After the split the input lives inside the chat column, not lost.
  const input = screen.getByPlaceholderText(/dream trip/i)
  expect(document.querySelector('.workspace__chat').contains(input)).toBe(true)
})

test('an older itinerary card re-opens that version in the canvas', async () => {
  const geo = { hotel: null, days: [{ day: 1, title: 'Day one', places: [] }] }
  vi.stubGlobal('fetch', queuedFetch([
    ['data: {"type":"token","content":"# Rome plan one"}\n\n', `data: ${JSON.stringify({ type: 'end', is_itinerary: true, geo })}\n\n`],
    ['data: {"type":"token","content":"# Rome plan two"}\n\n', `data: ${JSON.stringify({ type: 'end', is_itinerary: true, is_edit: true, edit_summary: 'swap' })}\n\n`],
  ]))

  render(<App />)
  fireEvent.click(screen.getByText('Plan a 3-day trip to Rome on a medium budget'))
  await waitFor(() => expect(document.querySelector('.workspace__canvas').textContent).toContain('Rome plan one'))

  // A follow-up edit produces a second version; the canvas follows the latest.
  fireEvent.change(screen.getByPlaceholderText(/dream trip/i), { target: { value: 'swap the hotel' } })
  fireEvent.click(screen.getByTitle('Send'))
  await waitFor(() => expect(document.querySelector('.workspace__canvas').textContent).toContain('Rome plan two'))

  // Clicking the first (ready) card brings that earlier version back into the canvas.
  fireEvent.click(screen.getByText('Itinerary ready'))
  const canvas = document.querySelector('.workspace__canvas').textContent
  expect(canvas).toContain('Rome plan one')
  expect(canvas).not.toContain('Rome plan two')
})

test('regenerate in the canvas streams a fresh plan and swaps the canvas to it', async () => {
  const geo = { hotel: null, days: [{ day: 1, title: 'Day one', places: [] }] }
  vi.stubGlobal('fetch', queuedFetch([
    ['data: {"type":"token","content":"# Rome plan one"}\n\n', `data: ${JSON.stringify({ type: 'end', is_itinerary: true, geo })}\n\n`],
    ['data: {"type":"token","content":"# Rome plan two"}\n\n', `data: ${JSON.stringify({ type: 'end', is_itinerary: true, is_edit: false, geo })}\n\n`],
  ]))

  render(<App />)
  fireEvent.click(screen.getByText('Plan a 3-day trip to Rome on a medium budget'))
  await waitFor(() => expect(document.querySelector('.workspace__canvas').textContent).toContain('Rome plan one'))

  fireEvent.click(screen.getByRole('button', { name: /regenerate/i }))
  await waitFor(() => expect(document.querySelector('.workspace__canvas').textContent).toContain('Rome plan two'))
})

test('a new chat collapses the split back to full-width chat', async () => {
  const geo = { hotel: null, days: [{ day: 1, title: 'Day one', places: [] }] }
  vi.stubGlobal('fetch', streamingFetch([
    'data: {"type":"token","content":"# Trip to Rome"}\n\n',
    `data: ${JSON.stringify({ type: 'end', is_itinerary: true, geo })}\n\n`,
  ]))

  render(<App />)
  fireEvent.click(screen.getByText('Romantic weekend in Paris for two'))
  await waitFor(() => expect(document.querySelector('.workspace')).not.toBeNull())

  fireEvent.click(screen.getByText('New chat'))
  expect(document.querySelector('.workspace')).toBeNull()
  expect(screen.getByText(/Where shall we/i)).toBeInTheDocument()
})
