// Centralized error-code -> user-friendly-message mapping — see Prompt 11
// "Error Handling": "Create a centralized frontend error mapper... Do not
// display raw backend stack traces or exception strings."

import { ApiError } from './client'

const MESSAGES_BY_CODE: Record<string, string> = {
  GRAPH_UNAVAILABLE: 'The knowledge graph is temporarily unavailable. Some features are degraded.',
  VECTOR_INDEX_UNAVAILABLE: 'Semantic search is temporarily unavailable.',
  EMBEDDING_PROVIDER_UNAVAILABLE: 'The embedding model is temporarily unavailable.',
  ANALYSIS_ALREADY_RUNNING: 'An analysis is already running for this repository.',
  ANALYSIS_FAILED: 'Repository analysis failed.',
  SYMBOL_NOT_FOUND: 'No matching symbol was found in this repository.',
  AMBIGUOUS_SYMBOL: 'That name matches more than one symbol — please be more specific.',
  INVALID_REQUEST: 'That request was not valid.',
  VALIDATION_ERROR: 'That request was not valid.',
  NOT_FOUND: 'The requested item could not be found.',
  CONFLICT: 'This conflicts with the current state of the resource.',
  UNSUPPORTED_MEDIA_TYPE: 'That file type is not supported.',
  PAYLOAD_TOO_LARGE: 'That file is too large.',
  UNSAFE_ARCHIVE: 'That archive failed a safety check and was rejected.',
  INVALID_GIT_URL: 'That is not a supported public HTTPS Git URL.',
  GIT_HOST_NOT_ALLOWED: 'Only GitHub and GitLab repository URLs are supported right now.',
  GIT_CLONING_DISABLED: 'Cloning a repository from a URL is disabled on this server.',
  GIT_CLONE_FAILED: 'Cloning that repository failed.',
  INVALID_TRAVERSAL_PARAMETER: 'That graph request was out of the allowed bounds.',
  NETWORK_ERROR: 'Could not reach the backend. Check your connection and try again.',
  REQUEST_TIMEOUT: 'The request took too long and was cancelled.',
}

/** A short, safe, human-readable message for any error thrown by
 * `apiRequest` — never leaks a raw exception string. */
export function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return MESSAGES_BY_CODE[error.code] ?? error.message
  }
  if (error instanceof Error) {
    return 'Something unexpected went wrong.'
  }
  return 'Something unexpected went wrong.'
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}
