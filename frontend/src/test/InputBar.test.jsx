import { render, screen, fireEvent } from '@testing-library/react'
import InputBar from '../components/InputBar'
import { buildQuotedMessage } from '../quote'

test('sends the typed text with no quote when none is pending', () => {
  const onSend = vi.fn()
  render(<InputBar onSend={onSend} isStreaming={false} onStop={() => {}} />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'plan rome' } })
  fireEvent.click(screen.getByTitle('Send'))
  expect(onSend).toHaveBeenCalledWith('plan rome')
})

test('shows the pending quote as a chip and removes it on dismiss', () => {
  const onClearQuote = vi.fn()
  render(
    <InputBar onSend={() => {}} isStreaming={false} onStop={() => {}} quote="Day 2: Trastevere" onClearQuote={onClearQuote} />,
  )
  expect(screen.getByText('Day 2: Trastevere')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /remove quoted selection/i }))
  expect(onClearQuote).toHaveBeenCalledTimes(1)
})

test('sending with a pending quote includes the quote then clears it', () => {
  const onSend = vi.fn()
  const onClearQuote = vi.fn()
  render(
    <InputBar onSend={onSend} isStreaming={false} onStop={() => {}} quote="Day 2: Trastevere" onClearQuote={onClearQuote} />,
  )
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'make this cheaper' } })
  fireEvent.click(screen.getByTitle('Send'))
  expect(onSend).toHaveBeenCalledWith(buildQuotedMessage('Day 2: Trastevere', 'make this cheaper'))
  expect(onClearQuote).toHaveBeenCalledTimes(1)
})
