// A status indicator that never relies on color alone — see Prompt 11
// "Accessibility": "status not communicated by color alone." Every status
// gets its own short text label and a distinct icon glyph.

export type BadgeTone = 'success' | 'warning' | 'error' | 'neutral' | 'info'

const TONE_CLASSES: Record<BadgeTone, string> = {
  success: 'bg-emerald-950 text-emerald-300 ring-emerald-800',
  warning: 'bg-amber-950 text-amber-300 ring-amber-800',
  error: 'bg-red-950 text-red-300 ring-red-800',
  neutral: 'bg-slate-800 text-slate-300 ring-slate-700',
  info: 'bg-sky-950 text-sky-300 ring-sky-800',
}

const TONE_ICON: Record<BadgeTone, string> = {
  success: '✓', // check
  warning: '⚠', // warning triangle
  error: '✕', // cross
  neutral: '●', // dot
  info: '↻', // refresh-ish
}

export function StatusBadge({
  label,
  tone,
  title,
}: {
  label: string
  tone: BadgeTone
  title?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE_CLASSES[tone]}`}
      title={title}
    >
      <span aria-hidden="true">{TONE_ICON[tone]}</span>
      {label}
    </span>
  )
}

const SUBSYSTEM_TONE: Record<string, BadgeTone> = {
  READY: 'success',
  NOT_STARTED: 'neutral',
  PENDING: 'info',
  RUNNING: 'info',
  PARTIAL: 'warning',
  STALE: 'warning',
  FAILED: 'error',
}

export function SubsystemStatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = SUBSYSTEM_TONE[status] ?? 'neutral'
  return <StatusBadge label={label ?? status} tone={tone} />
}
