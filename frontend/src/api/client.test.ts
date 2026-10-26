import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, ApiError } from './client'

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
}

describe('apiRequest', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns parsed JSON on a successful response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ok: true }))

    const result = await apiRequest<{ ok: boolean }>('/health/live')

    expect(result).toEqual({ ok: true })
  })

  it('omits undefined/null search params from the request URL', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}))

    await apiRequest('/symbols/search', {
      searchParams: { q: 'login', limit: undefined, symbol_type: null },
    })

    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toContain('q=login')
    expect(calledUrl).not.toContain('limit=')
    expect(calledUrl).not.toContain('symbol_type=')
  })

  it('throws an ApiError built from the backend error contract on a non-2xx response', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          error: { code: 'SYMBOL_NOT_FOUND', message: 'No such symbol.', retryable: false, details: {} },
          request_id: 'req-123',
        },
        { status: 404 },
      ),
    )

    await expect(apiRequest('/repositories/repo-1/symbols/missing')).rejects.toMatchObject({
      code: 'SYMBOL_NOT_FOUND',
      message: 'No such symbol.',
      requestId: 'req-123',
      status: 404,
    })
  })

  it('falls back to a generic UNKNOWN_ERROR for a non-JSON error body', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('<html>502</html>', { status: 502 }))

    const error = await apiRequest('/repositories').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('UNKNOWN_ERROR')
    expect((error as ApiError).retryable).toBe(true)
  })

  it('maps a fetch-level network failure to a retryable NETWORK_ERROR', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))

    const error = await apiRequest('/repositories').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('NETWORK_ERROR')
    expect((error as ApiError).retryable).toBe(true)
  })

  it('returns undefined for a 204 No Content response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))

    const result = await apiRequest('/repositories/repo-1')

    expect(result).toBeUndefined()
  })
})
