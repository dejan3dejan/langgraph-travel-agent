import { useState, useCallback } from 'react'

// Minimal analytics consent gate. Product analytics must call hasAnalyticsConsent() before firing;
// nothing is tracked until the user accepts. The analytics implementation itself lives elsewhere and
// plugs into this gate. The choice persists in localStorage so it survives reloads.
const CONSENT_KEY = 'atlas_analytics_consent'

// 'granted' | 'denied' | null (the user has not chosen yet).
export function getConsent() {
  return localStorage.getItem(CONSENT_KEY)
}

export function hasAnalyticsConsent() {
  return getConsent() === 'granted'
}

export function setAnalyticsConsent(granted) {
  localStorage.setItem(CONSENT_KEY, granted ? 'granted' : 'denied')
  // Let any already-mounted analytics code react to the change without a reload.
  window.dispatchEvent(new Event('atlas-consent-changed'))
}

// Drives the banner: it shows only while the choice is undecided.
export function useConsent() {
  const [decision, setDecision] = useState(() => getConsent())
  const accept = useCallback(() => { setAnalyticsConsent(true); setDecision('granted') }, [])
  const decline = useCallback(() => { setAnalyticsConsent(false); setDecision('denied') }, [])
  return { decided: decision !== null, granted: decision === 'granted', accept, decline }
}
