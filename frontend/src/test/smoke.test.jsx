import { render, screen } from '@testing-library/react'
import Welcome from '../components/Welcome'

test('Welcome renders its heading and prompt chips', () => {
  render(<Welcome onPrompt={() => {}} />)
  expect(screen.getByText(/Where shall we/i)).toBeInTheDocument()
  expect(screen.getByText(/Romantic weekend in Paris/i)).toBeInTheDocument()
})
