import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AuthModal from '../components/AuthModal'

function makeAuth(overrides = {}) {
  return {
    error: null,
    busy: false,
    login: vi.fn(async () => true),
    register: vi.fn(async () => true),
    forgotPassword: vi.fn(async () => ({ ok: true })),
    ...overrides,
  }
}

test('forgot-password flow asks for the email and confirms without revealing account existence', async () => {
  const auth = makeAuth()
  render(<AuthModal auth={auth} onClose={() => {}} />)

  fireEvent.click(screen.getByRole('button', { name: /forgot password/i }))
  fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'a@b.com' } })
  fireEvent.click(screen.getByRole('button', { name: /send reset link/i }))

  await waitFor(() => expect(auth.forgotPassword).toHaveBeenCalledWith('a@b.com'))
  expect(screen.getByText(/check your inbox/i)).toBeInTheDocument()
})

test('default mode signs in', async () => {
  const auth = makeAuth()
  const onClose = vi.fn()
  render(<AuthModal auth={auth} onClose={onClose} />)

  fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'a@b.com' } })
  fireEvent.change(screen.getByPlaceholderText(/password/i), { target: { value: 'secret1' } })
  fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))

  await waitFor(() => expect(auth.login).toHaveBeenCalledWith('a@b.com', 'secret1'))
})
