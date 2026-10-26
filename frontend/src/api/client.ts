// Centralized fetch handling — see Prompt 11 "API Client": base URL, JSON
// parsing, the backend's standardized error contract, request-id
// extraction, multipart upload, and timeouts. No component should call
// `fetch()` directly.

import type { ApiErrorBody } from '../types/api'

const RAW_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
// Historically this env var has been the bare origin (see
// docker-compose.yml / .env.example) — the `/api/v1` prefix is appended
// here rather than baked into the env var, so existing deployments/dev
// setups keep working unchanged.
export const API_BASE_URL = `${RAW_BASE_URL.replace(/\/+$/, '')}/api/v1`

const DEFAULT_TIMEOUT_MS = 30_000

/** Thrown for every non-2xx response. Carries the backend's own error
 * code/message/retryable/details plus the request id, when the backend
 * followed its standard error contract — falls back to a safe generic
 * shape otherwise (e.g. a network-level failure, or a non-JSON 502 from
 * an intermediary). Never carries a raw stack trace. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryable: boolean
  readonly details: Record<string, unknown>
  readonly requestId: string | null

  constructor(options: {
    status: number
    code: string
    message: string
    retryable: boolean
    details: Record<string, unknown>
    requestId: string | null
  }) {
    super(options.message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.retryable = options.retryable
    this.details = options.details
    this.requestId = options.requestId
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) {
    return false
  }
  const error = (value as { error?: unknown }).error
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get('x-request-id')
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // Non-JSON error body (e.g. a proxy's own 502 page) — fall through
    // to the generic mapping below rather than throwing here.
  }

  if (isApiErrorBody(body)) {
    return new ApiError({
      status: response.status,
      code: body.error.code,
      message: body.error.message,
      retryable: body.error.retryable,
      details: body.error.details ?? {},
      requestId: body.request_id ?? requestId,
    })
  }

  return new ApiError({
    status: response.status,
    code: 'UNKNOWN_ERROR',
    message: `Request failed with status ${response.status}.`,
    retryable: response.status >= 500,
    details: {},
    requestId,
  })
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  json?: unknown
  formData?: FormData
  searchParams?: Record<string, string | number | boolean | undefined | null>
  signal?: AbortSignal
  timeoutMs?: number
}

function buildUrl(path: string, searchParams?: RequestOptions['searchParams']): string {
  const url = new URL(`${API_BASE_URL}${path}`)
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.toString()
}

/** The one place every HTTP request to the backend goes through. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  )
  // Let an externally-supplied signal (e.g. component unmount) also abort.
  options.signal?.addEventListener('abort', () => controller.abort())

  const headers: Record<string, string> = {}
  const authToken = sessionStorage.getItem('codegraph_access_token')
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  let body: BodyInit | undefined

  if (options.formData) {
    body = options.formData
    // Never set Content-Type manually for FormData — the browser must
    // set the multipart boundary itself.
  } else if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.searchParams), {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: controller.signal,
    })
  } catch {
    clearTimeout(timeout)
    if (controller.signal.aborted) {
      throw new ApiError({
        status: 0,
        code: 'REQUEST_TIMEOUT',
        message: 'The request took too long and was cancelled.',
        retryable: true,
        details: {},
        requestId: null,
      })
    }
    throw new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Could not reach the backend. Check your connection and try again.',
      retryable: true,
      details: {},
      requestId: null,
    })
  } finally {
    clearTimeout(timeout)
  }

  if (!response.ok) {
    throw await toApiError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
