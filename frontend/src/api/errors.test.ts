import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { friendlyErrorMessage, isApiError } from './errors'

describe('friendlyErrorMessage', () => {
  it('maps a known backend error code to its friendly message', () => {
    const error = new ApiError({
      status: 503,
      code: 'GRAPH_UNAVAILABLE',
      message: 'neo4j.exceptions.ServiceUnavailable: connection refused at 10.0.0.4:7687',
      retryable: true,
      details: {},
      requestId: 'req-1',
    })

    expect(friendlyErrorMessage(error)).toBe(
      'The knowledge graph is temporarily unavailable. Some features are degraded.',
    )
  })

  it('falls back to the backend message for an unrecognized error code, never a raw exception string', () => {
    const error = new ApiError({
      status: 500,
      code: 'SOME_NEW_CODE',
      message: 'A safe backend-authored message.',
      retryable: false,
      details: {},
      requestId: null,
    })

    expect(friendlyErrorMessage(error)).toBe('A safe backend-authored message.')
  })

  it('never surfaces a raw JS error message for a non-ApiError', () => {
    expect(friendlyErrorMessage(new TypeError('Cannot read properties of undefined'))).toBe(
      'Something unexpected went wrong.',
    )
    expect(friendlyErrorMessage('a raw string thrown by accident')).toBe(
      'Something unexpected went wrong.',
    )
  })
})

describe('isApiError', () => {
  it('narrows only real ApiError instances', () => {
    expect(isApiError(new ApiError({ status: 400, code: 'X', message: 'x', retryable: false, details: {}, requestId: null }))).toBe(true)
    expect(isApiError(new Error('plain'))).toBe(false)
    expect(isApiError('not an error')).toBe(false)
  })
})
