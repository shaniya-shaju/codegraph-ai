import type { ReactNode } from 'react'

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded border border-dashed border-slate-800 px-6 py-16 text-center">
      <h3 className="text-base font-medium text-slate-200">{title}</h3>
      <p className="max-w-md text-sm text-slate-400">{description}</p>
      {action}
    </div>
  )
}
