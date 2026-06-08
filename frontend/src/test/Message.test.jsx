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
