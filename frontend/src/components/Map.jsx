import { Fragment, useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Popup, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './Map.css'
import { dayColor } from '../dayColors'

// HTML pins instead of Leaflet's default image marker, which 404s under the bundler and can't be
// colored per day anyway.
function pin(color, label) {
  return L.divIcon({
    className: 'map-pin',
    html: `<span class="map-pin__dot" style="background:${color}">${label}</span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  })
}

// Frame the view to every plotted point once, on mount.
function FitBounds({ points }) {
  const map = useMap()
  useEffect(() => {
    if (points.length) map.fitBounds(points, { padding: [36, 36] })
  }, [map, points])
  return null
}

// A point is plottable only with finite coordinates; a partially-geocoded plan can carry places
// with no lat/lon, and Leaflet throws on (undefined, undefined).
function hasCoords(p) {
  return p && Number.isFinite(p.lat) && Number.isFinite(p.lon)
}

export default function Map({ geo }) {
  const hotel = hasCoords(geo?.hotel) ? geo.hotel : null
  const points = []
  if (hotel) points.push([hotel.lat, hotel.lon])
  ;(geo?.days || []).forEach((d) => d.places.filter(hasCoords).forEach((p) => points.push([p.lat, p.lon])))

  // Nothing geocoded means nothing to plot, whether the days are missing, empty, or coordinate-less.
  if (points.length === 0) {
    return (
      <div className="map-fallback" role="note">
        We couldn&apos;t pin this itinerary on a map. Its locations weren&apos;t geocoded.
      </div>
    )
  }

  return (
    <div className="map-view">
      <MapContainer className="map-view__canvas" center={points[0]} zoom={13} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={points} />

        {hotel && (
          <Marker position={[hotel.lat, hotel.lon]} icon={pin('#111827', '★')}>
            <Popup>{hotel.name || 'Your base'}</Popup>
          </Marker>
        )}

        {(geo.days || []).map((d) => {
          const color = dayColor(d.day)
          const places = d.places.filter(hasCoords)
          const stops = places.map((p) => [p.lat, p.lon])
          // Route line returns to the base when there is one, so each day reads as a loop.
          const line = hotel ? [[hotel.lat, hotel.lon], ...stops, [hotel.lat, hotel.lon]] : stops
          return (
            <Fragment key={d.day}>
              {line.length > 1 && <Polyline positions={line} pathOptions={{ color, weight: 3, opacity: 0.7 }} />}
              {places.map((p, i) => (
                <Marker key={`${d.day}-${i}`} position={[p.lat, p.lon]} icon={pin(color, d.day)}>
                  <Tooltip>{`Day ${d.day}`}</Tooltip>
                  <Popup>{p.name}</Popup>
                </Marker>
              ))}
            </Fragment>
          )
        })}
      </MapContainer>

      <ul className="map-legend">
        {(geo.days || []).map((d) => (
          <li key={d.day} className="map-legend__item">
            <span className="map-legend__swatch" style={{ background: dayColor(d.day) }} />
            {`Day ${d.day} · ${d.title || d.label}`}
          </li>
        ))}
      </ul>
    </div>
  )
}
