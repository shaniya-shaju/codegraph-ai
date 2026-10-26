import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <p className="text-4xl">🔍</p>
      <h1 className="text-lg font-semibold text-slate-100">Page not found</h1>
      <p className="max-w-sm text-sm text-slate-400">
        The page you're looking for doesn't exist, or the link may be out of date.
      </p>
      <Link
        to="/"
        className="mt-2 rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500"
      >
        Back to dashboard
      </Link>
    </div>
  )
}
