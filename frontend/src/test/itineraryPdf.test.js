import { buildExportHtml, downloadItineraryPdf, exportItineraryPdf } from '../export/itineraryPdf'

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
    mapHtml: '<img id="route-map" src="data:image/png;base64,AAAA" />',
  })
  expect(html).toContain('<title>Trip to Rome</title>')
  expect(html).toContain('Trip to Rome')
  expect(html).toContain('Walk the forum')
  expect(html).toContain('<img id="route-map"')
})

test('renders a day card per day with its shared palette color', () => {
  const html = buildExportHtml({ title: 'Trip to Rome', bodyHtml: '', geo: GEO, mapHtml: '' })
  expect((html.match(/class="export-card"/g) || []).length).toBe(2)
  expect(html).toContain('Ancient core')
  expect(html).toContain('Vatican')
  expect(html).toContain('Colosseum')
  expect(html).toContain('#2563eb')
  expect(html).toContain('#db2777')
})

test('links each day-card stop to google maps directions', () => {
  const html = buildExportHtml({ title: 'Trip to Rome', bodyHtml: '', geo: GEO, mapHtml: '' })
  expect(html).toContain('href="https://www.google.com/maps/dir/?api=1&amp;destination=Colosseum"')
})

test('still produces a document when there is no geo', () => {
  const html = buildExportHtml({ title: 'Trip', bodyHtml: '<p>hi</p>', geo: null, mapHtml: '' })
  expect(html).toContain('<title>Trip</title>')
  expect(html).toContain('hi')
  expect(html).not.toContain('class="export-card"')
})

afterEach(() => {
  vi.restoreAllMocks()
  delete URL.createObjectURL
  delete URL.revokeObjectURL
  document.querySelectorAll('iframe').forEach((f) => f.remove())
})

test('downloadItineraryPdf posts the assembled document and triggers a file download', async () => {
  const blob = new Blob(['%PDF'], { type: 'application/pdf' })
  global.fetch = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob })
  URL.createObjectURL = vi.fn(() => 'blob:abc')
  URL.revokeObjectURL = vi.fn()
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

  await downloadItineraryPdf({ title: 'Trip to Rome', bodyHtml: '<p>Forum</p>', geo: GEO })

  expect(global.fetch).toHaveBeenCalledWith('/api/export/pdf', expect.objectContaining({ method: 'POST' }))
  const body = JSON.parse(global.fetch.mock.calls[0][1].body)
  expect(body.filename).toBe('Trip to Rome')
  expect(body.html).toContain('Trip to Rome')
  expect(body.html).toContain('Forum')
  expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
  expect(click).toHaveBeenCalled()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:abc')
})

test('downloadItineraryPdf throws when the server rejects the export', async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 })
  await expect(downloadItineraryPdf({ title: 'Trip', bodyHtml: '', geo: null })).rejects.toThrow(/503/)
})

test('exportItineraryPdf falls back to the print path when the server export fails', async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 })
  vi.spyOn(console, 'error').mockImplementation(() => {})

  await exportItineraryPdf({ title: 'Trip', bodyHtml: '<p>x</p>', geo: GEO })

  // The print fallback mounts a hidden iframe to carry the document into the print dialog.
  expect(document.querySelector('iframe')).not.toBeNull()
})
