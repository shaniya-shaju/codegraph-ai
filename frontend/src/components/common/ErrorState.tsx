import { useState } from 'react'
import { friendlyErrorMessage, isApiError } from '../../api/errors'

/** Shows a safe, friendly message for any error, with the raw code and
 * request id available behind an expandable "technical details" toggle
 * — see Prompt 11 "Error Handling": "Show request ID in expandable
 * technical details if useful." Never renders a stack trace. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const [showDetails, setShowDetails] = useState(false)
  const message = friendlyErrorMessage(error)
  const apiError = isApiError(error) ? error : null

  return (
    <div className="rounded border border-red-900 bg-red-950/40 p-4 text-sm">
      <p className="flex items-center gap-2 text-red-300">
        <span aria-hidden="true">⚠</span>
        {message}
      </p>
      <div className="mt-2 flex items-center gap-3">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded border border-red-800 px-2 py-1 text-xs text-red-200 hover:bg-red-900/40"
          >
            Retry
          </button>
        ) : null}
        {apiError ? (
          <button
            type="button"
            onClick={() => setShowDetails((v) => !v)}
            className="text-xs text-red-400 underline hover:text-red-300"
            aria-expanded={showDetails}
          >
            {showDetails ? 'Hide' : 'Show'} technical details
          </button>
        ) : null}
      </div>
      {showDetails && apiError ? (
        <dl className="mt-2 space-y-1 text-xs text-red-400">
          <div>
            <dt className="inline font-medium">Code: </dt>
            <dd className="inline">{apiError.code}</dd>
          </div>
          {apiError.requestId ? (
            <div>
              <dt className="inline font-medium">Request ID: </dt>
              <dd className="inline font-mono">{apiError.requestId}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  )
}
