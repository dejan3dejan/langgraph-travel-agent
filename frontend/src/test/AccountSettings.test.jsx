import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AccountSettings from '../components/AccountSettings'

function makeAuth(overrides = {}) {
  return {
    user: { id: '1', username: 'bob', email: 'b@x.com', email_verified: true },
    updateProfile: vi.fn(async () => ({ ok: true, data: {} })),
    changePassword: vi.fn(async () => ({ ok: true })),
    deleteAccount: vi.fn(async () => ({ ok: true })),
    resendVerification: vi.fn(async () => ({ ok: true })),
    ...overrides,
  }
}

test('saves only the profile fields that changed', async () => {
  const auth = makeAuth()
  render(<AccountSettings auth={auth} onClose={() => {}} />)

  fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'bobby' } })
  fireEvent.click(screen.getByRole('button', { name: /save profile/i }))

  await waitFor(() => expect(auth.updateProfile).toHaveBeenCalledWith({ username: 'bobby' }))
  expect(screen.getByText(/profile updated/i)).toBeInTheDocument()
})

test('change password sends the current and new password', async () => {
  const auth = makeAuth()
  render(<AccountSettings auth={auth} onClose={() => {}} />)

  fireEvent.change(screen.getByPlaceholderText('Current password'), { target: { value: 'old' } })
  fireEvent.change(screen.getByPlaceholderText(/new password/i), { target: { value: 'newpass' } })
  fireEvent.click(screen.getByRole('button', { name: /change password/i }))

  await waitFor(() => expect(auth.changePassword).toHaveBeenCalledWith('old', 'newpass'))
})

test('shows a verification banner and resends when the email is unverified', async () => {
  const auth = makeAuth({ user: { username: 'bob', email: 'b@x.com', email_verified: false } })
  render(<AccountSettings auth={auth} onClose={() => {}} />)

  expect(screen.getByText(/not verified/i)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /resend link/i }))
  await waitFor(() => expect(auth.resendVerification).toHaveBeenCalled())
})

test('delete account asks for confirmation before calling the hook', async () => {
  const auth = makeAuth()
  render(<AccountSettings auth={auth} onClose={() => {}} />)

  // First click only reveals the confirm form; it must not delete yet.
  fireEvent.click(screen.getByRole('button', { name: /delete my account/i }))
  expect(auth.deleteAccount).not.toHaveBeenCalled()

  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: /permanently delete/i }))
  await waitFor(() => expect(auth.deleteAccount).toHaveBeenCalledWith('pw'))
})
