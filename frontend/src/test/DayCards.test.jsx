import { render, screen } from '@testing-library/react'
import DayCards from '../components/DayCards'

const TWO_DAYS = {
  hotel: { name: 'Hotel Roma', lat: 41.89, lon: 12.49 },
  days: [
    { day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', kind: 'activity' }] },
    {
      day: 2,
      title: 'Vatican side',
      places: [
        { name: 'Vatican', kind: 'activity' },
        { name: 'Trattoria', kind: 'restaurant' },
      ],
    },
  ],
}

test('renders nothing when there is no geo or no days', () => {
  const { container, rerender } = render(<DayCards geo={null} />)
  expect(container).toBeEmptyDOMElement()
  rerender(<DayCards geo={{ hotel: null, days: [] }} />)
  expect(container).toBeEmptyDOMElement()
})

test('renders a card per day with its title and ordered stops', () => {
  render(<DayCards geo={TWO_DAYS} />)
  expect(screen.getByText('Ancient core')).toBeInTheDocument()
  expect(screen.getByText('Vatican side')).toBeInTheDocument()
  expect(screen.getByText('Colosseum')).toBeInTheDocument()
  expect(screen.getByText('Vatican')).toBeInTheDocument()
  expect(screen.getByText('Trattoria')).toBeInTheDocument()
  // a restaurant stop is tagged as food
  expect(screen.getByText('Food')).toBeInTheDocument()
})

test('falls back to the legacy label when the day has no title', () => {
  const geo = { hotel: null, days: [{ day: 3, label: 'Across town', places: [{ name: 'Park', kind: 'place' }] }] }
  render(<DayCards geo={geo} />)
  expect(screen.getByText('Across town')).toBeInTheDocument()
  expect(screen.getByText('Park')).toBeInTheDocument()
})
