import { dayColor } from '../dayColors'

// Builds a real street map for the PDF export by compositing OpenStreetMap raster tiles onto a
// canvas, then drawing the day-colored routes and numbered markers on top. The tiles send
// Access-Control-Allow-Origin, so loading them with crossOrigin keeps the canvas untainted and
// toDataURL() works; the resulting PNG is inlined into the export, so the server-side PDF render
// needs no network of its own. The schematic SVG (staticMap.js) stays as the fallback.
//
// OSM's tile usage policy expects light, attributed use; a few tiles per export is fine, but a
// production deployment with real traffic should point TILE_URL at a proper tile provider.

const TILE = 256
const TILE_URL = (z, x, y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`
const HOTEL_COLOR = '#111827'

function hasCoords(p) {
  return p && Number.isFinite(p.lat) && Number.isFinite(p.lon)
}

// Slippy-map projection: longitude/latitude to fractional tile coordinates at a zoom level.
export function lonToTileX(lon, z) {
  return ((lon + 180) / 360) * 2 ** z
}

export function latToTileY(lat, z) {
  const rad = (lat * Math.PI) / 180
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 2 ** z
}

// The largest zoom at which the bounding box still fits inside width x height (with a margin so
// markers aren't flush to the edge). Pure, so the framing is unit-testable.
export function chooseZoom(bounds, width, height, { minZoom = 2, maxZoom = 16, margin = 0.85 } = {}) {
  const { minLon, maxLon, minLat, maxLat } = bounds
  for (let z = maxZoom; z >= minZoom; z--) {
    const spanX = (lonToTileX(maxLon, z) - lonToTileX(minLon, z)) * TILE
    // Latitude grows downward in tile space, so maxLat is the smaller y.
    const spanY = (latToTileY(minLat, z) - latToTileY(maxLat, z)) * TILE
    if (spanX <= width * margin && spanY <= height * margin) return z
  }
  return minZoom
}

function collectPoints(geo) {
  const hotel = hasCoords(geo?.hotel) ? geo.hotel : null
  const points = []
  if (hotel) points.push(hotel)
  ;(geo?.days || []).forEach((d) => (d.places || []).filter(hasCoords).forEach((p) => points.push(p)))
  return { hotel, points }
}

function bounds(points) {
  const lons = points.map((p) => p.lon)
  const lats = points.map((p) => p.lat)
  return { minLon: Math.min(...lons), maxLon: Math.max(...lons), minLat: Math.min(...lats), maxLat: Math.max(...lats) }
}

function loadTile(z, x, y) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = TILE_URL(z, x, y)
  })
}

function drawPin(ctx, x, y, color, label) {
  ctx.beginPath()
  ctx.arc(x, y, 11, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.fill()
  ctx.lineWidth = 2
  ctx.strokeStyle = '#ffffff'
  ctx.stroke()
  ctx.fillStyle = '#ffffff'
  ctx.font = '700 12px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, x, y + 1)
}

// Resolve to a PNG data URL of the route map, or null when there is nothing to plot or anything
// goes wrong (no canvas in the environment, a tile fails to load). Callers fall back to the SVG.
export async function buildTileMapDataUrl(geo, { width = 600, height = 380 } = {}) {
  const { hotel, points } = collectPoints(geo)
  if (points.length === 0) return null

  try {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    canvas.width = width
    canvas.height = height

    const b = bounds(points)
    const z = chooseZoom(b, width, height)
    const centerX = ((lonToTileX(b.minLon, z) + lonToTileX(b.maxLon, z)) / 2) * TILE
    const centerY = ((latToTileY(b.minLat, z) + latToTileY(b.maxLat, z)) / 2) * TILE
    const originX = centerX - width / 2
    const originY = centerY - height / 2
    const toPx = (p) => [lonToTileX(p.lon, z) * TILE - originX, latToTileY(p.lat, z) * TILE - originY]

    const maxTile = 2 ** z - 1
    const tx0 = Math.floor(originX / TILE)
    const tx1 = Math.floor((originX + width) / TILE)
    const ty0 = Math.floor(originY / TILE)
    const ty1 = Math.floor((originY + height) / TILE)

    const jobs = []
    for (let tx = tx0; tx <= tx1; tx++) {
      for (let ty = ty0; ty <= ty1; ty++) {
        if (tx < 0 || ty < 0 || tx > maxTile || ty > maxTile) continue
        jobs.push(
          loadTile(z, tx, ty).then((img) => ctx.drawImage(img, tx * TILE - originX, ty * TILE - originY)),
        )
      }
    }
    await Promise.all(jobs)

    ctx.lineJoin = 'round'
    ;(geo.days || []).forEach((d) => {
      const stops = (d.places || []).filter(hasCoords).map(toPx)
      const line = hotel ? [toPx(hotel), ...stops, toPx(hotel)] : stops
      if (line.length < 2) return
      ctx.globalAlpha = 0.7
      ctx.strokeStyle = dayColor(d.day)
      ctx.lineWidth = 3
      ctx.beginPath()
      line.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
      ctx.stroke()
    })
    ctx.globalAlpha = 1
    ;(geo.days || []).forEach((d) => {
      ;(d.places || []).filter(hasCoords).forEach((p) => {
        const [x, y] = toPx(p)
        drawPin(ctx, x, y, dayColor(d.day), String(d.day))
      })
    })
    if (hotel) {
      const [x, y] = toPx(hotel)
      drawPin(ctx, x, y, HOTEL_COLOR, '★')
    }

    // OSM attribution is required by the tile usage policy.
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.textBaseline = 'bottom'
    const note = '© OpenStreetMap'
    ctx.fillStyle = 'rgba(255,255,255,0.75)'
    ctx.fillRect(width - ctx.measureText(note).width - 8, height - 16, ctx.measureText(note).width + 8, 16)
    ctx.fillStyle = '#3a4453'
    ctx.fillText(note, width - 4, height - 3)

    // JPEG, not PNG: the map is photographic, and this keeps the inlined image around 150KB instead
    // of ~700KB, which matters because it travels in the export request body.
    return canvas.toDataURL('image/jpeg', 0.9)
  } catch {
    return null
  }
}
