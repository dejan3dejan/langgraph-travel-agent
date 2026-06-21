import { render, screen, fireEvent } from '@testing-library/react'
import FeedbackForm from '../components/FeedbackForm'

test('send is disabled until there is a rating or a note', () => {
  render(<FeedbackForm onSubmit={() => {}} />)
  const send = screen.getByRole('button', { name: /send/i })
  expect(send).toBeDisabled()

  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'nice' } })
  expect(send).toBeEnabled()
})

test('rating a star alone enables send and submits the rating with no note', () => {
  const onSubmit = vi.fn()
  render(<FeedbackForm onSubmit={onSubmit} />)
  fireEvent.click(screen.getByRole('button', { name: /4 stars/i }))
  fireEvent.click(screen.getByRole('button', { name: /send/i }))
  expect(onSubmit).toHaveBeenCalledWith({ rating: 4, message: null })
})

test('submits both rating and trimmed message together', () => {
  const onSubmit = vi.fn()
  render(<FeedbackForm onSubmit={onSubmit} />)
  fireEvent.click(screen.getByRole('button', { name: /5 stars/i }))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '  loved B  ' } })
  fireEvent.click(screen.getByRole('button', { name: /send/i }))
  expect(onSubmit).toHaveBeenCalledWith({ rating: 5, message: 'loved B' })
})

test('clicking the active star again clears the rating', () => {
  const onSubmit = vi.fn()
  render(<FeedbackForm onSubmit={onSubmit} />)
  const third = screen.getByRole('button', { name: /3 stars/i })
  fireEvent.click(third)
  fireEvent.click(third)
  // rating cleared, so with no note send is disabled again
  expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
})
