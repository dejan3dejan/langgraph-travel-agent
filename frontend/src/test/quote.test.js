import { buildQuotedMessage } from '../quote'

test('returns the plain text when there is no quote', () => {
  expect(buildQuotedMessage(null, 'make day 2 cheaper')).toBe('make day 2 cheaper')
  expect(buildQuotedMessage('   ', 'make day 2 cheaper')).toBe('make day 2 cheaper')
})

test('prefixes the selection as a blockquote ahead of the message', () => {
  const out = buildQuotedMessage('Day 2: Trastevere food crawl', 'swap this for something cheaper')
  expect(out).toContain('> Day 2: Trastevere food crawl')
  expect(out).toContain('swap this for something cheaper')
  expect(out.indexOf('> Day 2')).toBeLessThan(out.indexOf('swap this'))
})

test('quotes every line of a multi-line selection', () => {
  const out = buildQuotedMessage('Day 2\nLunch at noon', 'reorder these')
  expect(out).toContain('> Day 2')
  expect(out).toContain('> Lunch at noon')
})

test('clamps a long selection so the message stays under the backend cap', () => {
  const long = 'x'.repeat(900)
  const out = buildQuotedMessage(long, 'fix this')
  expect(out).toContain('...')
  expect(out).not.toContain('x'.repeat(600))
  expect(out.length).toBeLessThan(700)
})
