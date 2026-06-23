import { describe, it, expect, vi, beforeEach } from 'vitest'

const posthog = { init: vi.fn(), capture: vi.fn(), identify: vi.fn(), reset: vi.fn() }
vi.mock('posthog-js', () => ({ default: posthog }))

// Drive consent through a mock of the gate the privacy chip owns. consentState flips what
// hasAnalyticsConsent() returns; dispatching the gate's event triggers the wrapper to re-sync.
let consentState = false
vi.mock('../consent', () => ({ hasAnalyticsConsent: () => consentState }))

function grantConsent() {
  consentState = true
  window.dispatchEvent(new Event('atlas-consent-changed'))
}

function withdrawConsent() {
  consentState = false
  window.dispatchEvent(new Event('atlas-consent-changed'))
}

// Each test exercises a fresh module instance so armed state does not leak between cases.
async function freshModule() {
  vi.resetModules()
  return import('../analytics.js')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.unstubAllEnvs()
  consentState = false
})

describe('analytics wrapper', () => {
  it('is a no-op when no write key is configured, even with consent', async () => {
    consentState = true
    const a = await freshModule()
    await a.init()
    a.track(a.events.APP_ENTERED, { is_retry: false })
    a.identify('user-1')
    expect(posthog.init).not.toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
  })

  it('does not load or send until consent is granted, even with a key', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
    const a = await freshModule()
    await a.init()
    a.track(a.events.PLAN_REQUESTED, { is_retry: false, is_regenerate: false })
    expect(posthog.init).not.toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
  })

  it('arms and forwards events once key and consent are both present at init', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
    consentState = true
    const a = await freshModule()
    await a.init()
    a.track(a.events.ITINERARY_DELIVERED, { is_edit: false, day_count: 3 })
    expect(posthog.init).toHaveBeenCalledOnce()
    expect(posthog.capture).toHaveBeenCalledWith('itinerary_delivered', { is_edit: false, day_count: 3 })
  })

  it('arms when consent is granted after init via the gate event', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
    const a = await freshModule()
    await a.init()
    expect(posthog.init).not.toHaveBeenCalled()
    grantConsent()
    await new Promise((resolve) => setTimeout(resolve))
    a.track(a.events.APP_ENTERED)
    // init may be called by listeners that earlier fresh-module imports left on the shared window;
    // the point is this module armed and forwarded the event.
    expect(posthog.init).toHaveBeenCalled()
    expect(posthog.capture).toHaveBeenCalledWith('app_entered', undefined)
  })

  it('identifies by id only', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
    consentState = true
    const a = await freshModule()
    await a.init()
    a.identify('user-42')
    expect(posthog.identify).toHaveBeenCalledWith('user-42')
  })

  it('ignores an empty identify so an anonymous user is never tied to a blank id', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
    consentState = true
    const a = await freshModule()
    await a.init()
    a.identify(undefined)
    expect(posthog.identify).not.toHaveBeenCalled()
  })

  it('stops sending and clears identity when consent is withdrawn', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
    consentState = true
    const a = await freshModule()
    await a.init()
    withdrawConsent()
    a.track(a.events.APP_ENTERED)
    expect(posthog.reset).toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
  })

  it('exposes the seven funnel events as a stable taxonomy', async () => {
    const a = await freshModule()
    expect(Object.keys(a.events)).toHaveLength(7)
    expect(a.events.LANDING_VIEWED).toBe('landing_viewed')
    expect(a.events.TRIP_SAVED).toBe('trip_saved')
  })
})
