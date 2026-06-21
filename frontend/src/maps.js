// A Google Maps directions link to a stop. Coordinates are used when we have them (exact, and no
// ambiguity over which "Trattoria"); otherwise we fall back to the place name. Omitting the origin
// lets Google route from the user's current location, which is what "give me directions" wants.
export function directionsUrl(place) {
  const hasCoords = place && Number.isFinite(place.lat) && Number.isFinite(place.lon)
  const destination = hasCoords ? `${place.lat},${place.lon}` : place?.name || ''
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}`
}
