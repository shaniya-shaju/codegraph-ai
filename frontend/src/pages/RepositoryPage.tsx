import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { triggerAnalysis } from '../api/analysis'
import { getRepository } from '../api/repositories'
import { ErrorState } from '../components/common/ErrorState'
import { Skeleton } from '../components/common/Skeleton'
import { SubsystemStatusBadge } from '../components/common/StatusBadge'
import { AnalysisProgress } from '../features/analysis/AnalysisProgress'
import { AnalysisStatusCards } from '../features/analysis/AnalysisStatusCards'
import { useAnalysisProgress } from '../features/analysis/useAnalysisProgress'
import { DeleteRepositoryDialog } from '../features/repositories/DeleteRepositoryDialog'
import { formatRelativeOrDate } from '../utils/format'

const RUNNING_STATUSES = new Set(['RUNNING', 'PENDING', 'NOT_STARTED'])

/** `/repositories/:repositoryId` — see Prompt 11 "Repository Overview
 * Page". */
export function RepositoryPage() {
  const { repositoryId } = useParams<{ repositoryId: string }>()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const queryClient = useQueryClient()

  const repositoryQuery = useQuery({
    queryKey: ['repository', repositoryId],
    queryFn: ({ signal }) => getRepository(repositoryId as string, signal),
    enabled: Boolean(repositoryId),
  })
  const analysisQuery = useAnalysisProgress(repositoryId)

  const analyzeMutation = useMutation({
    mutationFn: (force: boolean) => triggerAnalysis(repositoryId as string, force),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['analysis', repositoryId] })
    },
  })

  if (repositoryQuery.isPending || analysisQuery.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (repositoryQuery.isError) {
    return <ErrorState error={repositoryQuery.error} onRetry={() => repositoryQuery.refetch()} />
  }

  const repository = repositoryQuery.data
  const state = analysisQuery.data
  const isRunning = state ? RUNNING_STATUSES.has(state.overall_status) : false
  const isStale = state?.overall_status === 'STALE'
  const isPartial = state?.overall_status === 'PARTIAL'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">{repository?.name}</h1>
          <p className="mt-1 text-sm text-slate-400">
            {repository?.source_type === 'git_url' ? 'Git' : 'ZIP upload'} ·{' '}
            {repository?.source_location}
            {repository?.commit_sha ? ` · ${repository.commit_sha.slice(0, 8)}` : ''}
          </p>
          <p className="text-xs text-slate-500">
            Last analysis: {formatRelativeOrDate(state?.completed_at ?? null)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {state ? <SubsystemStatusBadge status={state.overall_status} label={`Overall: ${state.overall_status}`} /> : null}
          <Link
            to={`/repositories/${repositoryId}/assistant`}
            className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
          >
            Ask questions
          </Link>
          <button
            type="button"
            disabled={analyzeMutation.isPending || isRunning}
            onClick={() => analyzeMutation.mutate(isStale)}
            className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            {isStale ? 'Reanalyze' : 'Analyze'}
          </button>
          <button
            type="button"
            onClick={() => setDeleteOpen(true)}
            className="rounded border border-red-900 px-3 py-1.5 text-sm text-red-300 hover:bg-red-950/50"
          >
            Delete
          </button>
        </div>
      </div>

      {isRunning && state ? <AnalysisProgress state={state} /> : null}

      {isPartial && state ? (
        <div className="rounded border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-300">
          Analysis completed partially — one or more subsystems failed. See the status cards
          below for details.
          {state.errors.length > 0 ? (
            <ul className="mt-1 list-inside list-disc text-xs">
              {state.errors.map((err) => (
                <li key={err}>{err}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {isStale && state ? (
        <div className="rounded border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-300">
          Repository content has changed since the last analysis. Reanalyze for current results.
        </div>
      ) : null}

      {state ? <AnalysisStatusCards state={state} /> : null}

      {repository?.error_message ? (
        <p className="text-xs text-slate-500">Note: {repository.error_message}</p>
      ) : null}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Files" value={repository?.file_count} />
        <Stat label="Graph nodes" value={state?.graph_node_count} />
        <Stat label="Graph relationships" value={state?.graph_relationship_count} />
        <Stat label="Vector chunks" value={state?.vector_chunk_count} />
      </div>

      <DeleteRepositoryDialog
        repository={deleteOpen && repository ? repository : null}
        onClose={() => setDeleteOpen(false)}
        navigateAfterDelete
      />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-3">
      <p className="text-lg font-semibold text-slate-100">{value ?? '—'}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  )
}
