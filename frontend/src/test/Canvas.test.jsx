import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Canvas from '../components/Canvas'

// Map is lazy and pulls in Leaflet, so stub it; its own behavior is covered by Map.test.
vi.mock('../components/Map', () => ({
  default: ({ geo }) => <div data-testid="canvas-map">{geo ? 'map' : 'no-geo'}</div>,
}))

const GEO = {
  hotel: null,
  days: [{ day: 1, title: 'Ancient core', places: [{ name: 'Colosseum', kind: 'activity' }] }],
}

test('shows the trip title in the header, taken from the itinerary heading', () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  expect(document.querySelector('.canvas__header')).toHaveTextContent('Trip to Rome')
})

test('falls back to a generic header when the itinerary has no heading', () => {
  render(<Canvas itinerary={{ content: 'no heading here' }} geo={null} />)
  expect(document.querySelector('.canvas__header')).toHaveTextContent(/itinerary/i)
})

test('renders the day cards and the map alongside the itinerary', async () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  expect(screen.getByText('Ancient core')).toBeInTheDocument()
  expect(await screen.findByTestId('canvas-map')).toHaveTextContent('map')
})

test('copies the itinerary markdown to the clipboard', async () => {
  const writeText = vi.fn().mockResolvedValue()
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} />)
  fireEvent.click(screen.getByRole('button', { name: /copy/i }))

  await waitFor(() => expect(writeText).toHaveBeenCalledWith('# Trip to Rome\n## Day 1'))
})

test('regenerate action calls onRegenerate', () => {
  const onRegenerate = vi.fn()
  render(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} onRegenerate={onRegenerate} isStreaming={false} />)
  fireEvent.click(screen.getByRole('button', { name: /regenerate/i }))
  expect(onRegenerate).toHaveBeenCalledTimes(1)
})

test('regenerate shows an in-progress state and is disabled while streaming', () => {
  const onRegenerate = vi.fn()
  render(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} onRegenerate={onRegenerate} isStreaming />)
  const btn = screen.getByRole('button', { name: /regenerating/i })
  expect(btn).toBeDisabled()
  fireEvent.click(btn)
  expect(onRegenerate).not.toHaveBeenCalled()
})

vi.mock('../export/itineraryPdf', () => ({ exportItineraryPdf: vi.fn() }))
import { exportItineraryPdf } from '../export/itineraryPdf'

test('export action hands the title, rendered body, and geo to the pdf pipeline', async () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1\nWalk the forum' }} geo={GEO} />)
  fireEvent.click(screen.getByRole('button', { name: /export pdf/i }))

  await waitFor(() => expect(exportItineraryPdf).toHaveBeenCalledTimes(1))
  const arg = exportItineraryPdf.mock.calls[0][0]
  expect(arg.title).toBe('Trip to Rome')
  expect(arg.geo).toBe(GEO)
  expect(arg.bodyHtml).toContain('Walk the forum')
})

test('shows a share action only when onShare is provided', () => {
  const { rerender } = render(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} />)
  expect(screen.queryByRole('button', { name: /share/i })).toBeNull()

  rerender(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} onShare={() => {}} shareStatus="idle" />)
  expect(screen.getByRole('button', { name: /share/i })).toBeInTheDocument()
})

test('share action calls onShare', () => {
  const onShare = vi.fn()
  render(<Canvas itinerary={{ content: '# Trip to Rome' }} geo={GEO} onShare={onShare} shareStatus="idle" />)
  fireEvent.click(screen.getByRole('button', { name: /share/i }))
  expect(onShare).toHaveBeenCalledTimes(1)
})

test('share action reflects the copied status and is disabled while sharing', () => {
  const { rerender } = render(
    <Canvas itinerary={{ content: '# Trip' }} geo={GEO} onShare={() => {}} shareStatus="sharing" />,
  )
  expect(screen.getByRole('button', { name: /sharing/i })).toBeDisabled()

  rerender(<Canvas itinerary={{ content: '# Trip' }} geo={GEO} onShare={() => {}} shareStatus="copied" />)
  expect(screen.getByRole('button', { name: /link copied/i })).toBeInTheDocument()
})

test('shows a stop-sharing action only once a link is live, and it calls onUnshare', () => {
  const onUnshare = vi.fn()
  const { rerender } = render(
    <Canvas itinerary={{ content: '# Trip' }} geo={GEO} onShare={() => {}} onUnshare={onUnshare} isShared={false} />,
  )
  expect(screen.queryByRole('button', { name: /stop sharing/i })).toBeNull()

  rerender(
    <Canvas itinerary={{ content: '# Trip' }} geo={GEO} onShare={() => {}} onUnshare={onUnshare} isShared />,
  )
  fireEvent.click(screen.getByRole('button', { name: /stop sharing/i }))
  expect(onUnshare).toHaveBeenCalledTimes(1)
})

function stubSelection(text, anchorNode, rangeRect = { top: 0, bottom: 0, left: 0, right: 0 }) {
  const sel = {
    toString: () => text,
    rangeCount: text ? 1 : 0,
    anchorNode,
    getRangeAt: () => ({ getBoundingClientRect: () => rangeRect }),
    removeAllRanges: vi.fn(),
  }
  vi.spyOn(window, 'getSelection').mockReturnValue(sel)
  return sel
}

afterEach(() => vi.restoreAllMocks())

test('selecting itinerary text reveals an add-to-chat button that quotes the selection', () => {
  const onAddToChat = vi.fn()
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} onAddToChat={onAddToChat} />)
  const details = document.querySelector('.canvas__details')
  stubSelection('Day 1 in Rome', details)

  fireEvent.mouseUp(details)
  fireEvent.click(screen.getByRole('button', { name: /add to chat/i }))

  expect(onAddToChat).toHaveBeenCalledWith('Day 1 in Rome')
  expect(screen.queryByRole('button', { name: /add to chat/i })).toBeNull()
})

test('floats the add-to-chat button just under the selection, relative to the scrolled body', () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} onAddToChat={() => {}} />)
  const details = document.querySelector('.canvas__details')
  vi.spyOn(details, 'getBoundingClientRect').mockReturnValue({ top: 80, left: 40 })
  Object.defineProperty(details, 'scrollTop', { value: 50, configurable: true })
  stubSelection('Day 1 in Rome', details, { top: 200, bottom: 220, left: 120, right: 300 })

  fireEvent.mouseUp(details)

  const btn = screen.getByRole('button', { name: /add to chat/i })
  // bottom - container.top + scrollTop, and left - container.left
  expect(btn.style.top).toBe('190px')
  expect(btn.style.left).toBe('80px')
})

test('an empty selection does not show the add-to-chat button', () => {
  render(<Canvas itinerary={{ content: '# Trip to Rome\n## Day 1' }} geo={GEO} onAddToChat={() => {}} />)
  const details = document.querySelector('.canvas__details')
  stubSelection('', details)

  fireEvent.mouseUp(details)
  expect(screen.queryByRole('button', { name: /add to chat/i })).toBeNull()
})

test('rate action calls onRate, and is hidden in compare mode', () => {
  const onRate = vi.fn()
  const { rerender } = render(<Canvas itinerary={{ content: '# Trip' }} geo={GEO} onRate={onRate} />)
  fireEvent.click(screen.getByRole('button', { name: /rate this plan/i }))
  expect(onRate).toHaveBeenCalledTimes(1)

  rerender(<Canvas itinerary={{ content: '# A' }} geo={GEO} onRate={onRate} variant="A" onSelectVariant={() => {}} onKeepVariant={() => {}} />)
  expect(screen.queryByRole('button', { name: /rate this plan/i })).toBeNull()
})

test('compare: shows an A|B switch and a keep button, and hides the committed-plan actions', () => {
  render(
    <Canvas
      itinerary={{ content: '# Trip to Rome (A)' }}
      geo={GEO}
      variant="A"
      onSelectVariant={() => {}}
      onKeepVariant={() => {}}
      onRegenerate={() => {}}
      onShare={() => {}}
      shareStatus="idle"
      isStreaming={false}
    />,
  )
  expect(screen.getByRole('button', { name: /option a/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /option b/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /keep this one/i })).toBeInTheDocument()
  // regenerate/share belong to a committed itinerary, not an A/B draft
  expect(screen.queryByRole('button', { name: /regenerate/i })).toBeNull()
  expect(screen.queryByRole('button', { name: /^share$/i })).toBeNull()
})

test('compare: selecting a variant calls onSelectVariant', () => {
  const onSelectVariant = vi.fn()
  render(
    <Canvas itinerary={{ content: '# A' }} geo={GEO} variant="A" onSelectVariant={onSelectVariant} onKeepVariant={() => {}} />,
  )
  fireEvent.click(screen.getByRole('button', { name: /option b/i }))
  expect(onSelectVariant).toHaveBeenCalledWith('B')
})

test('compare: keep calls onKeepVariant with the active variant', () => {
  const onKeepVariant = vi.fn()
  render(
    <Canvas itinerary={{ content: '# B' }} geo={GEO} variant="B" onSelectVariant={() => {}} onKeepVariant={onKeepVariant} />,
  )
  fireEvent.click(screen.getByRole('button', { name: /keep this one/i }))
  expect(onKeepVariant).toHaveBeenCalledWith('B')
})

test('compare: keep is disabled while the variants are still streaming', () => {
  render(
    <Canvas itinerary={{ content: '# A' }} geo={GEO} variant="A" onSelectVariant={() => {}} onKeepVariant={() => {}} isStreaming />,
  )
  expect(screen.getByRole('button', { name: /keep this one/i })).toBeDisabled()
})

test('passes the edit summary through to the itinerary', () => {
  render(
    <Canvas
      itinerary={{ content: '# Trip', isUpdated: true, updatedSummary: 'swapped the Tuesday restaurant' }}
      geo={GEO}
    />,
  )
  expect(screen.getByText('Updated')).toBeInTheDocument()
  expect(screen.getByText(/swapped the Tuesday restaurant/)).toBeInTheDocument()
})
