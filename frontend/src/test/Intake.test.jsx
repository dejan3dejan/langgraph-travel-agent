import { render, screen, fireEvent } from '@testing-library/react'
import Intake from '../components/Intake'

test('Intake shows the field groups, a start button, and a skip link', () => {
  render(<Intake onComplete={() => {}} onSkip={() => {}} />)
  expect(screen.getByRole('button', { name: /start planning/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /skip for now/i })).toBeInTheDocument()
  expect(screen.getByText(/budget/i)).toBeInTheDocument()
  expect(screen.getByText(/dietary/i)).toBeInTheDocument()
})

test('Intake submits only the fields the user picked', () => {
  const onComplete = vi.fn()
  render(<Intake onComplete={onComplete} onSkip={() => {}} />)

  fireEvent.click(screen.getByRole('button', { name: 'Medium' }))
  fireEvent.click(screen.getByRole('button', { name: 'Food' }))
  fireEvent.click(screen.getByRole('button', { name: 'Vegetarian' }))
  fireEvent.click(screen.getByRole('button', { name: /start planning/i }))

  expect(onComplete).toHaveBeenCalledTimes(1)
  expect(onComplete).toHaveBeenCalledWith({
    budget: 'Medium',
    interests: ['food'],
    dietary: ['vegetarian'],
  })
})

test('Intake start with no selections submits an empty object', () => {
  const onComplete = vi.fn()
  render(<Intake onComplete={onComplete} onSkip={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /start planning/i }))
  expect(onComplete).toHaveBeenCalledWith({})
})

test('Intake toggling a chip off removes it from the payload', () => {
  const onComplete = vi.fn()
  render(<Intake onComplete={onComplete} onSkip={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Food' }))
  fireEvent.click(screen.getByRole('button', { name: 'Food' }))
  fireEvent.click(screen.getByRole('button', { name: /start planning/i }))
  expect(onComplete).toHaveBeenCalledWith({})
})

test('Intake skip calls onSkip and not onComplete', () => {
  const onComplete = vi.fn()
  const onSkip = vi.fn()
  render(<Intake onComplete={onComplete} onSkip={onSkip} />)
  fireEvent.click(screen.getByRole('button', { name: /skip for now/i }))
  expect(onSkip).toHaveBeenCalledTimes(1)
  expect(onComplete).not.toHaveBeenCalled()
})

test('Intake copy contains no em dashes', () => {
  const { container } = render(<Intake onComplete={() => {}} onSkip={() => {}} />)
  expect(container.textContent).not.toMatch(/—/)
})
