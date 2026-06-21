import { describe, it, expect } from 'vitest'
import { buildApiUrl } from '../api'

describe('buildApiUrl', () => {
  it('returns the path unchanged when no base is set (dev proxy)', () => {
    expect(buildApiUrl('', '/api/chat/stream')).toBe('/api/chat/stream')
  })

  it('prefixes an absolute base origin', () => {
    expect(buildApiUrl('https://api.example.com', '/api/users/me')).toBe('https://api.example.com/api/users/me')
  })

  it('strips a trailing slash on the base so paths do not double up', () => {
    expect(buildApiUrl('https://api.example.com/', '/api/share')).toBe('https://api.example.com/api/share')
  })

  it('keeps query strings intact', () => {
    expect(buildApiUrl('https://api.example.com', '/api/cache/test-similarity?q=paris')).toBe(
      'https://api.example.com/api/cache/test-similarity?q=paris',
    )
  })

  it('treats null or undefined base as empty', () => {
    expect(buildApiUrl(null, '/health')).toBe('/health')
    expect(buildApiUrl(undefined, '/health')).toBe('/health')
  })
})
