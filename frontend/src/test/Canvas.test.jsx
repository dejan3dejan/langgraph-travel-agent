import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Canvas from '../components/Canvas'

// Map is lazy and pulls in Leaflet, so stub it; its own behavior is covered by Map.test.
vi.mock('../components/Map', () => ({
  default: ({ geo }) => <div data-testid="canvas-map">{geo ? 'map' : 'no-geo'}</div>,
}))

const GEO = {
  hotel: null,
  days: [{ day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', kind: 'activity' }] }],
}

test('shows the trip title in the header, taken from the itinerary heading', () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  expect(document.querySelector('.canvas__header')).toHaveTextContent('Trip to Rome')
})

test('falls back to a generic header when the itinerary has no heading', () => {
  render(<Canvas itinerary={{ content: 'no heading here' }} geo={null} />)
  expect(document.querySelector('.canvas__header')).toHaveTextContent(/itinerary/i)
})

test('renders the day cards and the map alongside the itinerary', async () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  expect(screen.getByText('Ancient core')).toBeInTheDocument()
  expect(await screen.findByTestId('canvas-map')).toHaveTextContent('map')
})

test('copies the itinerary markdown to the clipboard', async () => {
  const writeText = vi.fn().mockResolvedValue()
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  fireEvent.click(screen.getByRole('button', { name: /copy/i }))

  await waitFor(() => expect(writeText).toHaveBeenCalledWith('# Trip to Rome\n## Day 1'))
})

test('regenerate action calls onRegenerate', () => {
  const onRegenerate = vi.fn()
  render(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} onRegenerate={onRegenerate} isStreaming={false} />)
  fireEvent.click(screen.getByRole('button', { name: /regenerate/i }))
  expect(onRegenerate).toHaveBeenCalledTimes(1)
})

test('regenerate shows an in-progress state and is disabled while streaming', () => {
  const onRegenerate = vi.fn()
  render(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} onRegenerate={onRegenerate} isStreaming />)
  const btn = screen.getByRole('button', { name: /regenerating/i })
  expect(btn).toBeDisabled()
  fireEvent.click(btn)
  expect(onRegenerate).not.toHaveBeenCalled()
})

test('passes the edit summary through to the itinerary', () => {
  render(
    <Canvas
      itinerary={{ content: '# Trip', isUpdated: true, updatedSummary: 'swapped the Tuesday restaurant' }}
      geo={GEO}
    />,
  )
  expect(screen.getByText('Updated')).toBeInTheDocument()
  expect(screen.getByText(/swapped the Tuesday restaurant/)).toBeInTheDocument()
})
