import { render, screen, fireEvent } from '@testing-library/react'
import ItineraryCard from '../components/ItineraryCard'

test('shows a ready label for a first itinerary', () => {
  render(<ItineraryCard onView={() => {}} />)
  expect(screen.getByText('Itinerary ready')).toBeInTheDocument()
})

test('shows an updated label and the edit summary', () => {
  render(<ItineraryCard isUpdated summary="swapped the Tuesday restaurant" onView={() => {}} />)
  expect(screen.getByText('Itinerary updated')).toBeInTheDocument()
  expect(screen.getByText(/swapped the Tuesday restaurant/)).toBeInTheDocument()
})

test('calls onView when clicked', () => {
  const onView = vi.fn()
  render(<ItineraryCard onView={onView} />)
  fireEvent.click(screen.getByRole('button'))
  expect(onView).toHaveBeenCalled()
})
