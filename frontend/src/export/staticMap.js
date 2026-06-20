import { dayColor } from '../dayColors'

// The live Leaflet canvas prints poorly, so the PDF gets this instead: a vector route map drawn from
// the same geo points and day colors as the on-screen map. No tiles, no API key, no network, which
// keeps it crisp in print and renderable in jsdom tests. It mirrors Map.jsx: a colored loop per day
// back to the hotel, a numbered pin per stop, and a star for the base.

const W = 600
const H = 380
const PAD = 30
const HOTEL_COLOR = '#111827'

function hasCoords(p) {
  return p && Number.isFinite(p.lat) && Number.isFinite(p.lon)
}

// Web Mercator, normalized to the unit square; bounds-fitting happens after projection.
function project(lat, lon) {
  const x = (lon + 180) / 360
  const rad = (lat * Math.PI) / 180
  const y = (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2
  return [x, y]
}

function fitter(projected) {
  const xs = projected.map((p) => p[0])
  const ys = projected.map((p) => p[1])
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  // Preserve aspect so a route doesn't stretch; fit the larger span and center the other axis.
  const span = Math.max(spanX, spanY)
  const offX = (span - spanX) / 2
  const offY = (span - spanY) / 2
  return ([x, y]) => [
    PAD + ((x - minX + offX) / span) * (W - 2 * PAD),
    PAD + ((y - minY + offY) / span) * (H - 2 * PAD),
  ]
}

function polyline(points, color) {
  const pts = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" opacity="0.6" />`
}

function pin([x, y], color, label, extraClass = '') {
  const cls = extraClass ? `export-pin ${extraClass}` : 'export-pin'
  return (
    `<g class="${cls}" transform="translate(${x.toFixed(1)},${y.toFixed(1)})">` +
    `<circle r="11" fill="${color}" stroke="#ffffff" stroke-width="2" />` +
    `<text text-anchor="middle" dy="4" font-size="11" font-weight="700" fill="#ffffff">${label}</text>` +
    `</g>`
  )
}

export function buildRouteMapSvg(geo) {
  const hotel = hasCoords(geo?.hotel) ? geo.hotel : null

  const dayPlaces = (geo?.days || []).map((d) => ({
    day: d.day,
    places: (d.places || []).filter(hasCoords),
  }))

  const all = []
  if (hotel) all.push([hotel.lat, hotel.lon])
  dayPlaces.forEach((d) => d.places.forEach((p) => all.push([p.lat, p.lon])))

  if (all.length === 0) {
    return '<p class="export-map-empty">Map unavailable: this itinerary wasn\'t geocoded.</p>'
  }

  const fit = fitter(all.map(([lat, lon]) => project(lat, lon)))
  const at = (lat, lon) => fit(project(lat, lon))
  const hotelXY = hotel ? at(hotel.lat, hotel.lon) : null

  const routes = dayPlaces
    .filter((d) => d.places.length)
    .map((d) => {
      const stops = d.places.map((p) => at(p.lat, p.lon))
      const line = hotelXY ? [hotelXY, ...stops, hotelXY] : stops
      return line.length > 1 ? polyline(line, dayColor(d.day)) : ''
    })
    .join('')

  const markers = dayPlaces
    .map((d) => d.places.map((p) => pin(at(p.lat, p.lon), dayColor(d.day), d.day)).join(''))
    .join('')

  const star = hotelXY ? pin(hotelXY, HOTEL_COLOR, '★', 'export-pin--hotel') : ''

  return (
    `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="export-map" role="img" aria-label="Trip route map">` +
    `<rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="#eef1f6" />` +
    routes +
    markers +
    star +
    `</svg>`
  )
}
