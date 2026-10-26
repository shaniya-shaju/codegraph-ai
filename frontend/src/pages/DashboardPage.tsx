import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { triggerAnalysis } from '../api/analysis'
import { listRepositories } from '../api/repositories'
import { ErrorState } from '../components/common/ErrorState'
import { SkeletonRows } from '../components/common/Skeleton'
import { EmptyState } from '../components/common/EmptyState'
import { DeleteRepositoryDialog } from '../features/repositories/DeleteRepositoryDialog'
import { ImportRepositoryDialog } from '../features/repositories/ImportRepositoryDialog'
import { RepositoryCard } from '../features/repositories/RepositoryCard'
import type { Repository } from '../types/api'

/** `/` — see Prompt 11 "Dashboard Page". */
export function DashboardPage() {
  const [importOpen, setImportOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Repository | null>(null)
  const queryClient = useQueryClient()

  const repositoriesQuery = useQuery({
    queryKey: ['repositories'],
    queryFn: ({ signal }) => listRepositories(signal),
  })

  const analyzeMutation = useMutation({
    mutationFn: (repository: Repository) => triggerAnalysis(repository.repository_id, false),
    onSuccess: (_result, repository) => {
      void queryClient.invalidateQueries({ queryKey: ['analysis', repository.repository_id] })
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Repositories</h1>
          <p className="text-sm text-slate-400">
            Import a repository to build its knowledge graph and vector index.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setImportOpen(true)}
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500"
        >
          Import Repository
        </button>
      </div>

      {repositoriesQuery.isPending ? <SkeletonRows count={4} /> : null}
      {repositoriesQuery.isError ? (
        <ErrorState error={repositoriesQuery.error} onRetry={() => repositoriesQuery.refetch()} />
      ) : null}

      {repositoriesQuery.data && repositoriesQuery.data.length === 0 ? (
        <EmptyState
          title="No repositories yet"
          description="Upload a ZIP or clone a public Git repository to begin code analysis."
          action={
            <button
              type="button"
              onClick={() => setImportOpen(true)}
              className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500"
            >
              Import Repository
            </button>
          }
        />
      ) : null}

      {repositoriesQuery.data && repositoriesQuery.data.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {repositoriesQuery.data.map((repository) => (
            <RepositoryCard
              key={repository.repository_id}
              repository={repository}
              onDelete={setDeleteTarget}
              onAnalyze={(repo) => analyzeMutation.mutate(repo)}
            />
          ))}
        </div>
      ) : null}

      <ImportRepositoryDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <DeleteRepositoryDialog repository={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </div>
  )
}
