import { apiUrl } from '../api'
import { dayColor } from '../dayColors'
import { directionsUrl } from '../maps'
import { buildRouteMapSvg } from './staticMap'
import { buildTileMapDataUrl } from './tileMap'

const KIND_LABEL = { activity: 'Activity', restaurant: 'Food', place: 'Place' }

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
  ))
}

function dayCardsHtml(geo) {
  const days = geo?.days || []
  if (!days.length) return ''
  const cards = days.map((d) => {
    const color = dayColor(d.day)
    const title = escapeHtml(d.title || d.label || `Day ${d.day}`)
    // Each stop is a Google Maps link, so a tap on the printed plan opens directions to it.
    const stops = (d.places || []).map((p) => (
      `<li><a class="export-card__stop" href="${escapeHtml(directionsUrl(p))}">${escapeHtml(p.name)}</a>` +
      `<span class="export-card__kind">${escapeHtml(KIND_LABEL[p.kind] || 'Place')}</span></li>`
    )).join('')
    return (
      `<article class="export-card">` +
      `<header class="export-card__head">` +
      `<span class="export-card__badge" style="background:${color}">${escapeHtml(d.day)}</span>` +
      `<h3>${title}</h3></header>` +
      `<ol>${stops}</ol></article>`
    )
  }).join('')
  return `<section class="export-cards">${cards}</section>`
}

// A self-contained print document: the trip title, the static route map, the rendered itinerary, and
// the day cards, with all styling inlined. It always renders on white paper, so raw light-mode colors
// here are intentional and never need the app's dark-theme tokens.
export function buildExportHtml({ title, bodyHtml, geo, mapHtml }) {
  const safeTitle = escapeHtml(title || 'Your itinerary')
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${safeTitle}</title>
<style>
  @page { margin: 18mm; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1b2430;
    line-height: 1.5;
  }
  .export-brand { font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase; color: #6b7686; }
  .export-title { margin: 4px 0 16px; font-size: 26px; font-weight: 800; letter-spacing: -0.02em; }
  .export-map, .export-map-empty { width: 100%; height: auto; margin-bottom: 22px; }
  img.export-map { border-radius: 14px; display: block; }
  .export-map-empty { color: #6b7686; font-size: 13px; }
  .markdown-body h1 { display: none; }
  .markdown-body h2 { font-size: 17px; margin: 18px 0 6px; }
  .markdown-body h3 { font-size: 14px; margin: 12px 0 4px; }
  .markdown-body p, .markdown-body li { font-size: 13px; }
  .markdown-body table { border-collapse: collapse; width: 100%; font-size: 12px; }
  .markdown-body th, .markdown-body td { border: 1px solid #d7dde6; padding: 5px 8px; text-align: left; }
  .export-cards { margin-top: 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .export-card { border: 1px solid #e1e6ee; border-radius: 10px; padding: 12px 14px; break-inside: avoid; }
  .export-card__head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .export-card__badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%; color: #fff; font-size: 12px; font-weight: 700;
  }
  .export-card h3 { margin: 0; font-size: 14px; }
  .export-card ol { margin: 0; padding-left: 18px; }
  .export-card li { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; padding: 2px 0; }
  .export-card__stop { color: #1b2430; text-decoration: none; }
  .export-card__kind { color: #8a93a3; font-size: 11px; white-space: nowrap; }
</style>
</head>
<body>
  <p class="export-brand">Atlas travel companion</p>
  <h1 class="export-title">${safeTitle}</h1>
  ${mapHtml || ''}
  <div class="markdown-body">${bodyHtml || ''}</div>
  ${dayCardsHtml(geo)}
</body>
</html>`
}

function safeFilename(title) {
  return (title || 'itinerary').replace(/[^A-Za-z0-9 _-]+/g, '').trim().slice(0, 80) || 'itinerary'
}

// Prefer a real OSM street map (composited to an inlined PNG); fall back to the schematic SVG route
// map when there are no coordinates or tiles can't be loaded, so the export always shows something.
async function buildMapHtml(geo) {
  try {
    const dataUrl = await buildTileMapDataUrl(geo)
    if (dataUrl) return `<img class="export-map" src="${dataUrl}" alt="Trip route map" />`
  } catch {
    // fall through to the SVG
  }
  return buildRouteMapSvg(geo)
}

// Render server-side (headless Chromium) and download the PDF directly. This is the crisp, one-click
// path that also works on mobile, where the browser print dialog is clumsy.
export async function downloadItineraryPdf({ title, bodyHtml, geo }) {
  const html = buildExportHtml({ title, bodyHtml, geo, mapHtml: await buildMapHtml(geo) })
  const res = await fetch(apiUrl('/api/export/pdf'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ html, filename: title }),
  })
  if (!res.ok) throw new Error(`Export failed: ${res.status}`)

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${safeFilename(title)}.pdf`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// What the canvas calls. Prefer the server download; if the backend is unreachable or the renderer is
// down, fall back to the always-available browser print path rather than failing silently.
export async function exportItineraryPdf({ title, bodyHtml, geo }) {
  try {
    await downloadItineraryPdf({ title, bodyHtml, geo })
  } catch (err) {
    console.error('PDF download failed, falling back to print', err)
    printItineraryDocument({ title, bodyHtml, geo })
  }
}

// Render the document into a hidden iframe and hand it to the browser's print dialog (the user picks
// "Save as PDF"). An iframe avoids popup blockers, and an <img>-free inline SVG map avoids the
// cross-origin canvas tainting that would break an html2canvas/jsPDF pipeline.
export function printItineraryDocument({ title, bodyHtml, geo }) {
  // The print fallback is synchronous, so it uses the schematic SVG rather than the async tile map.
  const html = buildExportHtml({ title, bodyHtml, geo, mapHtml: buildRouteMapSvg(geo) })

  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.style.position = 'fixed'
  frame.style.right = '0'
  frame.style.bottom = '0'
  frame.style.width = '0'
  frame.style.height = '0'
  frame.style.border = '0'
  document.body.appendChild(frame)

  const cleanup = () => {
    if (frame.parentNode) frame.parentNode.removeChild(frame)
  }

  frame.onload = () => {
    const win = frame.contentWindow
    if (!win) {
      cleanup()
      return
    }
    win.focus()
    win.print()
    // Give the print dialog a beat to read the document before the iframe is torn down.
    win.onafterprint = cleanup
    setTimeout(cleanup, 1000)
  }

  const doc = frame.contentDocument || frame.contentWindow?.document
  doc.open()
  doc.write(html)
  doc.close()
}
