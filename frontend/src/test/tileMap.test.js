import { chooseZoom, latToTileY, lonToTileX } from '../export/tileMap'

const TILE = 256

test('lonToTileX maps the prime meridian and antimeridian', () => {
  expect(lonToTileX(-180, 1)).toBeCloseTo(0)
  expect(lonToTileX(0, 1)).toBeCloseTo(1)
  expect(lonToTileX(180, 1)).toBeCloseTo(2)
})

test('latToTileY puts the equator in the middle', () => {
  expect(latToTileY(0, 1)).toBeCloseTo(1)
})

test('chooseZoom frames a small bbox tighter (higher zoom) than a wide one', () => {
  const tight = { minLon: 12.45, maxLon: 12.5, minLat: 41.88, maxLat: 41.92 }
  const wide = { minLon: 10, maxLon: 15, minLat: 40, maxLat: 45 }
  expect(chooseZoom(tight, 600, 380)).toBeGreaterThan(chooseZoom(wide, 600, 380))
})

test('chooseZoom picks a zoom whose bbox fits inside the canvas', () => {
  const b = { minLon: 12.45, maxLon: 12.5, minLat: 41.88, maxLat: 41.92 }
  const z = chooseZoom(b, 600, 380)
  const spanX = (lonToTileX(b.maxLon, z) - lonToTileX(b.minLon, z)) * TILE
  const spanY = (latToTileY(b.minLat, z) - latToTileY(b.maxLat, z)) * TILE
  expect(spanX).toBeLessThanOrEqual(600)
  expect(spanY).toBeLessThanOrEqual(380)
})
