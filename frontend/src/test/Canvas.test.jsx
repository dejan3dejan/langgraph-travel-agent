import { render, screen } from '@testing-library/react'
import Canvas from '../components/Canvas'

// Map is lazy and pulls in Leaflet, so stub it; its own behavior is covered by Map.test.
vi.mock('../components/Map', () => ({
  default: ({ geo }) => <div data-testid="canvas-map">{geo ? 'map' : 'no-geo'}</div>,
}))

const GEO = {
  hotel: null,
  days: [{ day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', kind: 'activity' }] }],
}

test('renders the itinerary markdown, day cards, and the map', async () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  expect(screen.getByText(/Trip to Rome/)).toBeInTheDocument()
  expect(screen.getByText('Ancient core')).toBeInTheDocument()
  expect(await screen.findByTestId('canvas-map')).toBeInTheDocument()
})

test('still mounts the map when there is no geo so its fallback can show', async () => {
  render(<Canvas itinerary={{ content: '# Trip' }} geo={null} />)
  expect(await screen.findByTestId('canvas-map')).toHaveTextContent('no-geo')
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
