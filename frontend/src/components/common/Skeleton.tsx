export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={`animate-pulse rounded bg-slate-800 ${className}`}
    />
  )
}

export function SkeletonRows({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-2" data-testid="skeleton-rows">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  )
}
