import { buildExportHtml } from '../export/itineraryPdf'

const GEO = {
  hotel: null,
  days: [
    { day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', kind: 'activity' }] },
    { day: 2, title: 'Vatican', places: [{ name: 'St Peter', kind: 'place' }] },
  ],
}

test('embeds the trip title, the rendered itinerary body, and the map', () => {
  const html = buildExportHtml({
    title: 'Trip to Rome',
    bodyHtml: '<h2>Day 1</h2><p>Walk the forum</p>',
    geo: GEO,
    mapSvg: '<svg id="route-map"></svg>',
  })
  expect(html).toContain('<title>Trip to Rome</title>')
  expect(html).toContain('Trip to Rome')
  expect(html).toContain('Walk the forum')
  expect(html).toContain('<svg id="route-map">')
})

test('renders a day card per day with its shared palette color', () => {
  const html = buildExportHtml({ title: 'Trip to Rome', bodyHtml: '', geo: GEO, mapSvg: '' })
  expect((html.match(/class="export-card"/g) || []).length).toBe(2)
  expect(html).toContain('Ancient core')
  expect(html).toContain('Vatican')
  expect(html).toContain('Colosseum')
  expect(html).toContain('#2563eb')
  expect(html).toContain('#db2777')
})

test('still produces a document when there is no geo', () => {
  const html = buildExportHtml({ title: 'Trip', bodyHtml: '<p>hi</p>', geo: null, mapSvg: '' })
  expect(html).toContain('<title>Trip</title>')
  expect(html).toContain('hi')
  expect(html).not.toContain('class="export-card"')
})
