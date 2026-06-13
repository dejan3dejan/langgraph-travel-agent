import { render, screen } from '@testing-library/react'
import Map from '../components/Map'

// Leaflet can't render in jsdom, so stub react-leaflet and leaflet to plain markers we can count.
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  Marker: ({ children }) => <div data-testid="marker">{children}</div>,
  Polyline: () => <div data-testid="polyline" />,
  Popup: ({ children }) => <div data-testid="popup">{children}</div>,
  Tooltip: ({ children }) => <div data-testid="tooltip">{children}</div>,
  useMap: () => ({ fitBounds: () => {} }),
}))

vi.mock('leaflet', () => ({ default: { divIcon: () => ({}) } }))

const TWO_DAYS = {
  hotel: { name: 'Hotel Roma', lat: 41.89, lon: 12.49 },
  days: [
    { day: 1, zone: 'near', label: 'Walkable', places: [{ name: 'Colosseum', lat: 41.89, lon: 12.492, kind: 'activity' }] },
    {
      day: 2,
      zone: 'medium',
      label: 'Short transit',
      places: [
        { name: 'Vatican', lat: 41.902, lon: 12.453, kind: 'activity' },
        { name: 'Trattoria', lat: 41.905, lon: 12.46, kind: 'restaurant' },
      ],
    },
  ],
}

test('C2.5: renders a fallback when there is no geo', () => {
  render(<Map geo={null} />)
  expect(screen.getByText(/couldn't pin this itinerary/i)).toBeInTheDocument()
})

test('C2.5: renders a fallback when no day has coordinates', () => {
  render(<Map geo={{ hotel: null, days: [] }} />)
  expect(screen.getByText(/couldn't pin this itinerary/i)).toBeInTheDocument()
})

test('C2.4: renders hotel + per-place markers, a route line per day, and a day legend', () => {
  render(<Map geo={TWO_DAYS} />)
  // hotel (1) + day 1 (1) + day 2 (2) = 4 markers
  expect(screen.getAllByTestId('marker')).toHaveLength(4)
  // one route line per day
  expect(screen.getAllByTestId('polyline')).toHaveLength(2)
  // legend reflects each day and its proximity label
  expect(screen.getByText(/Day 1 · Walkable/)).toBeInTheDocument()
  expect(screen.getByText(/Day 2 · Short transit/)).toBeInTheDocument()
})
