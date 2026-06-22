import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ResetPassword from '../components/ResetPassword'

afterEach(() => vi.unstubAllGlobals())

test('posts the token and new password, then confirms success', async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ status: 'reset' }) }))
  vi.stubGlobal('fetch', fetchMock)

  render(<ResetPassword token="tok123" />)
  fireEvent.change(screen.getByPlaceholderText(/new password/i), { target: { value: 'newpass' } })
  fireEvent.click(screen.getByRole('button', { name: /set new password/i }))

  await waitFor(() => expect(screen.getByText(/has been reset/i)).toBeInTheDocument())
  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body).toEqual({ token: 'tok123', new_password: 'newpass' })
})

test('shows the server error for an invalid or expired link', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: false, status: 400, json: async () => ({ detail: 'Invalid or expired reset link' }) })),
  )

  render(<ResetPassword token="bad" />)
  fireEvent.change(screen.getByPlaceholderText(/new password/i), { target: { value: 'newpass' } })
  fireEvent.click(screen.getByRole('button', { name: /set new password/i }))

  await waitFor(() => expect(screen.getByText(/invalid or expired reset link/i)).toBeInTheDocument())
})
