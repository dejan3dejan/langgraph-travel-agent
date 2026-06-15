import { render } from '@testing-library/react'
import CompassMark from '../components/CompassMark'

test('renders an svg mark', () => {
  const { container } = render(<CompassMark />)
  expect(container.querySelector('svg')).toBeInTheDocument()
})

test('draws from brand tokens, never a hardcoded hex', () => {
  const { container } = render(<CompassMark />)
  const html = container.innerHTML
  expect(html).toContain('var(--brand-forest)')
  expect(html).toContain('var(--brand-gold)')
  expect(html).not.toMatch(/#[0-9a-fA-F]{3,6}/)
})

test('standalone, it is announced as an image titled Atlas', () => {
  const { container } = render(<CompassMark />)
  const svg = container.querySelector('svg')
  expect(svg).toHaveAttribute('role', 'img')
  expect(container.querySelector('title')).toHaveTextContent('Atlas')
})

test('decorative, it is hidden from assistive tech', () => {
  const { container } = render(<CompassMark aria-hidden />)
  const svg = container.querySelector('svg')
  expect(svg).toHaveAttribute('aria-hidden', 'true')
  expect(svg).not.toHaveAttribute('role')
  expect(container.querySelector('title')).toBeNull()
})

test('honors the size prop', () => {
  const { container } = render(<CompassMark size={22} />)
  const svg = container.querySelector('svg')
  expect(svg).toHaveAttribute('width', '22')
  expect(svg).toHaveAttribute('height', '22')
})
