import { render, screen, waitFor } from '@testing-library/react'
import VerifyEmail from '../components/VerifyEmail'

afterEach(() => vi.unstubAllGlobals())

test('confirms the email on mount and posts the token', async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200 }))
  vi.stubGlobal('fetch', fetchMock)

  render(<VerifyEmail token="tok123" />)

  await waitFor(() => expect(screen.getByText(/your email is verified/i)).toBeInTheDocument())
  const body = JSON.parse(fetchMock.mock.calls[0][1].body)
  expect(body).toEqual({ token: 'tok123' })
})

test('shows a failure message for an invalid or expired link', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 400 })))

  render(<VerifyEmail token="bad" />)

  await waitFor(() => expect(screen.getByText(/invalid or has expired/i)).toBeInTheDocument())
})
