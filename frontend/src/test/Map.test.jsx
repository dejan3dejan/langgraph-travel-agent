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
    { day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', lat: 41.89, lon: 12.492, kind: 'activity' }] },
    {
      day: 2,
      title: 'Vatican side',
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

test('renders a fallback when days exist but no place has coordinates', () => {
  const NO_COORDS = {
    hotel: null,
    days: [{ day: 1, title: 'Arrival', places: [{ name: 'Hotel check-in', kind: 'activity' }] }],
  }
  render(<Map geo={NO_COORDS} />)
  expect(screen.getByText(/couldn't pin this itinerary/i)).toBeInTheDocument()
})

test('skips coordinate-less places but still plots the geocoded ones in a partial day', () => {
  const PARTIAL = {
    hotel: null,
    days: [
      {
        day: 1,
        title: 'Mixed',
        places: [
          { name: 'Pantheon', lat: 41.898, lon: 12.476, kind: 'activity' },
          { name: 'Ungeocoded spot', kind: 'activity' },
        ],
      },
    ],
  }
  render(<Map geo={PARTIAL} />)
  // only the place with coordinates becomes a marker
  expect(screen.getAllByTestId('marker')).toHaveLength(1)
})

test('C2.4: renders hotel + per-place markers, a route line per day, and a day legend', () => {
  render(<Map geo={TWO_DAYS} />)
  // hotel (1) + day 1 (1) + day 2 (2) = 4 markers
  expect(screen.getAllByTestId('marker')).toHaveLength(4)
  // one route line per day
  expect(screen.getAllByTestId('polyline')).toHaveLength(2)
  // legend reflects each day and its theme
  expect(screen.getByText(/Day 1 · Ancient core/)).toBeInTheDocument()
  expect(screen.getByText(/Day 2 · Vatican side/)).toBeInTheDocument()
})

test('C2.4: falls back to the proximity label for trips saved before day titles', () => {
  const OLD = {
    hotel: null,
    days: [{ day: 1, label: 'Walkable', places: [{ name: 'Park', lat: 41.9, lon: 12.5, kind: 'activity' }] }],
  }
  render(<Map geo={OLD} />)
  expect(screen.getByText(/Day 1 · Walkable/)).toBeInTheDocument()
})
