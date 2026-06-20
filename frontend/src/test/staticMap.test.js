import { buildRouteMapSvg } from '../export/staticMap'

const GEO = {
  hotel: { name: 'Hotel Roma', lat: 41.9, lon: 12.49 },
  days: [
    { day: 1, title: 'Ancient core', places: [
      { name: 'Colosseum', lat: 41.89, lon: 12.49 },
      { name: 'Forum', lat: 41.892, lon: 12.485 },
    ] },
    { day: 2, title: 'Vatican', places: [
      { name: 'St Peter', lat: 41.902, lon: 12.453 },
    ] },
  ],
}

test('renders one route polyline per day, colored by the shared day palette', () => {
  const svg = buildRouteMapSvg(GEO)
  expect(svg).toMatch(/^<svg/)
  expect((svg.match(/<polyline/g) || []).length).toBe(2)
  // Day 1 and day 2 hues from dayColors.js.
  expect(svg).toContain('#2563eb')
  expect(svg).toContain('#db2777')
})

test('plots a marker for every geocoded place plus the hotel star', () => {
  const svg = buildRouteMapSvg(GEO)
  // Three place markers carry their day number.
  expect((svg.match(/class="export-pin"/g) || []).length).toBe(3)
  expect(svg).toContain('export-pin--hotel')
  expect(svg).toContain('★')
})

test('omits the hotel star when the hotel has no coordinates', () => {
  const svg = buildRouteMapSvg({ ...GEO, hotel: null })
  expect(svg).not.toContain('export-pin--hotel')
  // Day 1 has two stops so its line stands without a base; day 2's lone stop can't form one.
  expect((svg.match(/<polyline/g) || []).length).toBe(1)
})

test('drops places that were never geocoded', () => {
  const geo = { hotel: null, days: [
    { day: 1, title: 'Mixed', places: [
      { name: 'Has coords', lat: 41.89, lon: 12.49 },
      { name: 'No coords' },
    ] },
  ] }
  expect((buildRouteMapSvg(geo).match(/class="export-pin"/g) || []).length).toBe(1)
})

test('falls back to a note when nothing is geocoded', () => {
  const svg = buildRouteMapSvg({ hotel: null, days: [{ day: 1, title: 'x', places: [{ name: 'a' }] }] })
  expect(svg).not.toMatch(/^<svg/)
  expect(svg).toMatch(/wasn't geocoded/i)
})
