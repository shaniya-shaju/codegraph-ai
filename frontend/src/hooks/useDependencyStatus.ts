import { useQuery } from '@tanstack/react-query'
import { getReadiness } from '../api/health'

// Polled, not on every render/interaction — see Prompt 11 "Readiness /
// Dependency Banner": "Do not spam requests."
const POLL_INTERVAL_MS = 20_000

export function useDependencyStatus() {
  return useQuery({
    queryKey: ['readiness'],
    queryFn: ({ signal }) => getReadiness(signal),
    refetchInterval: POLL_INTERVAL_MS,
    // A degraded/unavailable backend is a legitimate state, not a query
    // "error" the UI should retry aggressively for.
    retry: 1,
  })
}
