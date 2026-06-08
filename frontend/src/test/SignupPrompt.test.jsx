import { render, screen } from '@testing-library/react'
import SignupPrompt from '../components/SignupPrompt'

test('SignupPrompt shows the save-this-trip nudge and a sign-up CTA', () => {
  render(<SignupPrompt onSignUp={() => {}} onDismiss={() => {}} />)
  expect(screen.getByText(/save this trip/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /sign up/i })).toBeInTheDocument()
})
