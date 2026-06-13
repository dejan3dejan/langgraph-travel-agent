import { render, screen } from '@testing-library/react'
import Loader from '../components/Loader'

test('shows the label and is announced as a status', () => {
  render(<Loader label="Charting your trip" />)
  const region = screen.getByRole('status')
  expect(region).toHaveTextContent('Charting your trip')
})

test('defaults to the globe instrument', () => {
  const { container } = render(<Loader />)
  expect(container.querySelector('.loader--globe')).toBeInTheDocument()
})

test('renders the compass instrument when asked', () => {
  const { container } = render(<Loader variant="compass" />)
  expect(container.querySelector('.loader--compass')).toBeInTheDocument()
  expect(container.querySelector('.loader--globe')).not.toBeInTheDocument()
})

test('renders the radar instrument when asked', () => {
  const { container } = render(<Loader variant="radar" />)
  expect(container.querySelector('.loader--radar')).toBeInTheDocument()
  expect(container.querySelector('.loader__sweep')).toBeInTheDocument()
})
