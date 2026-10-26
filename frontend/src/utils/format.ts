export function formatRelativeOrDate(iso: string | null): string {
  if (!iso) return 'never'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return 'unknown'

  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.round(diffMs / 60_000)
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.round(diffHours / 24)
  if (diffDays < 30) return `${diffDays}d ago`
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function formatNumber(value: number | null): string {
  if (value === null) return '—'
  return value.toLocaleString()
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[_\s]+/)
    .map((word) => (word.length > 0 ? word[0].toUpperCase() + word.slice(1) : word))
    .join(' ')
}
