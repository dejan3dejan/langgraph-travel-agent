import { directionsUrl } from '../maps'

test('uses coordinates when the stop has them', () => {
  const url = directionsUrl({ name: 'Colosseum', lat: 41.89, lon: 12.49 })
  expect(url).toBe('https://www.google.com/maps/dir/?api=1&destination=41.89%2C12.49')
})

test('falls back to the place name without coordinates', () => {
  expect(directionsUrl({ name: 'Trattoria da Enzo' })).toBe(
    'https://www.google.com/maps/dir/?api=1&destination=Trattoria%20da%20Enzo',
  )
})

test('handles a missing place without throwing', () => {
  expect(directionsUrl(null)).toBe('https://www.google.com/maps/dir/?api=1&destination=')
})
