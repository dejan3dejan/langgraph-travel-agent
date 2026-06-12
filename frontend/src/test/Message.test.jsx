import { render, screen } from '@testing-library/react'
import Message from '../components/Message'

test('a finalized itinerary shows the prices-are-estimates note', () => {
  render(<Message role="ai" isItinerary content={'# Trip to Rome\n## Day 1: Colosseum'} />)
  expect(screen.getByText(/estimates/i)).toBeInTheDocument()
})

test('a plain chat reply does not show the estimates note', () => {
  render(<Message role="ai" content="How many days are you planning?" />)
  expect(screen.queryByText(/estimates/i)).not.toBeInTheDocument()
})

test('an edited itinerary shows an Updated badge', () => {
  render(<Message role="ai" isItinerary isUpdated content={'# Trip to Rome\n## Day 1'} />)
  expect(screen.getByText('Updated')).toBeInTheDocument()
})

test('a first-time itinerary shows no Updated badge', () => {
  render(<Message role="ai" isItinerary content={'# Trip to Rome\n## Day 1'} />)
  expect(screen.queryByText('Updated')).not.toBeInTheDocument()
})

test('an edited itinerary shows what changed next to the badge', () => {
  render(
    <Message role="ai" isItinerary isUpdated updatedSummary="swap the Tuesday restaurant" content={'# Trip to Rome'} />,
  )
  expect(screen.getByText('Updated')).toBeInTheDocument()
  expect(screen.getByText(/swap the Tuesday restaurant/)).toBeInTheDocument()
})
