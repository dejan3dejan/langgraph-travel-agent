// The backend caps a chat message at 2000 chars, so a long highlight has to be clamped or the
// quoted request would silently fail validation. Leave plenty of room for the user's own text.
const MAX_QUOTE_CHARS = 500

// Fold a selected slice of the itinerary into the next message as a markdown blockquote, so the
// model can see exactly which section the user is talking about. The endpoint only takes a plain
// message string, so there is no structured context field to use.
export function buildQuotedMessage(quote, text) {
  const trimmed = (quote || '').trim()
  if (!trimmed) return text

  const clamped =
    trimmed.length > MAX_QUOTE_CHARS ? trimmed.slice(0, MAX_QUOTE_CHARS).trimEnd() + '...' : trimmed
  const blockquote = clamped
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')

  return `Regarding this part of the itinerary:\n\n${blockquote}\n\n${text}`
}
