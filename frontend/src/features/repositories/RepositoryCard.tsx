import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getAnalysisState } from '../../api/analysis'
import { SubsystemStatusBadge } from '../../components/common/StatusBadge'
import type { Repository } from '../../types/api'
import { formatRelativeOrDate } from '../../utils/format'

/** One repository row on the dashboard — see Prompt 11 "Dashboard
 * Page": name, source type, created date, overall/parser/graph/vector
 * status, file count, last analyzed time, current/stale indicator,
 * Open/Analyze/Delete actions. */
export function RepositoryCard({
  repository,
  onDelete,
  onAnalyze,
}: {
  repository: Repository
  onDelete: (repository: Repository) => void
  onAnalyze: (repository: Repository) => void
}) {
  const analysisQuery = useQuery({
    queryKey: ['analysis', repository.repository_id],
    queryFn: ({ signal }) => getAnalysisState(repository.repository_id, signal),
  })
  const state = analysisQuery.data
  const isStale = state ? state.overall_status === 'STALE' : false

  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            to={`/repositories/${repository.repository_id}`}
            className="truncate text-sm font-semibold text-slate-100 hover:underline"
          >
            {repository.name}
          </Link>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {repository.source_type === 'git_url' ? 'Git' : 'ZIP upload'} ·{' '}
            {repository.source_location}
          </p>
        </div>
        {state ? (
          <SubsystemStatusBadge status={state.overall_status} />
        ) : (
          <SubsystemStatusBadge status={repository.status.toUpperCase()} />
        )}
      </div>

      {state ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          <SubsystemStatusBadge status={state.parser_status} label="Parser" />
          <SubsystemStatusBadge status={state.graph_status} label="Graph" />
          <SubsystemStatusBadge status={state.vector_status} label="Vector" />
        </div>
      ) : null}

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400">
        <div>
          <dt className="inline text-slate-500">Files: </dt>
          <dd className="inline">{repository.file_count ?? '—'}</dd>
        </div>
        <div>
          <dt className="inline text-slate-500">Created: </dt>
          <dd className="inline">{formatRelativeOrDate(repository.created_at)}</dd>
        </div>
        <div className="col-span-2">
          <dt className="inline text-slate-500">Last analyzed: </dt>
          <dd className="inline">{formatRelativeOrDate(repository.last_indexed_at)}</dd>
        </div>
      </dl>

      {isStale ? (
        <p className="mt-2 text-xs text-amber-400">
          Content changed since the last analysis — reanalyze for current results.
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-2">
        <Link
          to={`/repositories/${repository.repository_id}`}
          className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
        >
          Open
        </Link>
        <button
          type="button"
          onClick={() => onAnalyze(repository)}
          className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
        >
          {isStale ? 'Reanalyze' : 'Analyze'}
        </button>
        <button
          type="button"
          onClick={() => onDelete(repository)}
          className="ml-auto rounded border border-red-900 px-2.5 py-1 text-xs text-red-300 hover:bg-red-950/50"
        >
          Delete
        </button>
      </div>
    </div>
  )
}
