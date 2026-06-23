import { hasAnalyticsConsent } from './consent'

// Product analytics wrapper. This is the only module that touches the analytics SDK, so call sites
// stay a single track() line. The whole thing is a hard no-op until a write key is configured AND
// the user has granted consent through the consent gate, which keeps local dev, tests, and CI from
// emitting anything.
//
// Consent is owned by ./consent: nothing leaves the browser until hasAnalyticsConsent() is true.
// init() also listens for the gate's 'atlas-consent-changed' event so accepting or withdrawing in
// the banner arms or disarms tracking without a reload.
//
// Property hygiene: never pass PII or itinerary contents. Booleans, counts, and enums only. The
// taxonomy below is the full set of events; document any addition in analytics.md.
export const events = Object.freeze({
  LANDING_VIEWED: 'landing_viewed',
  APP_ENTERED: 'app_entered',
  PLAN_REQUESTED: 'plan_requested',
  ITINERARY_DELIVERED: 'itinerary_delivered',
  SIGNUP_PROMPT_SHOWN: 'signup_prompt_shown',
  SIGNUP_COMPLETED: 'signup_completed',
  TRIP_SAVED: 'trip_saved',
})

// Read lazily rather than caching at module load so consent granted after init() still arms.
function writeKey() {
  return import.meta.env.VITE_POSTHOG_KEY
}

function apiHost() {
  return import.meta.env.VITE_POSTHOG_HOST || 'https://eu.i.posthog.com'
}

let client = null
let loading = null
let wired = false

function armed() {
  return Boolean(writeKey()) && hasAnalyticsConsent()
}

// Load posthog-js on demand (off the first-paint bundle) and init it once both gates are open.
// Concurrent callers share the one in-flight import. Loading failures degrade to a logged no-op so
// analytics can never break the app.
function arm() {
  if (client || loading || !armed()) return loading
  loading = import('posthog-js')
    .then(({ default: posthog }) => {
      posthog.init(writeKey(), {
        api_host: apiHost(),
        capture_pageview: false,
        autocapture: false,
        persistence: 'localStorage',
      })
      client = posthog
    })
    .catch((err) => {
      console.warn('analytics: failed to load posthog-js', err)
    })
    .finally(() => {
      loading = null
    })
  return loading
}

function disarm() {
  // Clear the stored distinct id so a withdrawn user is no longer tracked.
  if (client) client.reset()
  client = null
}

function syncConsent() {
  if (hasAnalyticsConsent()) arm()
  else disarm()
}

export function init() {
  if (!wired) {
    wired = true
    window.addEventListener('atlas-consent-changed', syncConsent)
  }
  return arm()
}

export function track(event, props) {
  if (!client) return
  client.capture(event, props)
}

// Tie events to the account by id only, never email or username.
export function identify(userId) {
  if (!client || !userId) return
  client.identify(String(userId))
}

export function reset() {
  if (client) client.reset()
}
