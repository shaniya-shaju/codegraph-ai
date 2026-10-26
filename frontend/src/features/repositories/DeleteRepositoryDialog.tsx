import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { deleteRepository } from '../../api/repositories'
import { Dialog } from '../../components/common/Dialog'
import { ErrorState } from '../../components/common/ErrorState'
import type { Repository } from '../../types/api'

/** See Prompt 11 "Repository Delete Flow": confirmation dialog, warn on
 * partial cleanup rather than pretending complete success, navigate to
 * dashboard after success. */
export function DeleteRepositoryDialog({
  repository,
  onClose,
  navigateAfterDelete = false,
}: {
  repository: Repository | null
  onClose: () => void
  navigateAfterDelete?: boolean
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const mutation = useMutation({
    mutationFn: () => deleteRepository((repository as Repository).repository_id),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] })
      if (result.status === 'deleted') {
        onClose()
        if (navigateAfterDelete) navigate('/')
      }
    },
  })

  if (!repository) return null

  return (
    <Dialog open={Boolean(repository)} onClose={onClose} title={`Delete ${repository.name}?`}>
      <p className="text-sm text-slate-300">
        This removes repository analysis data, graph data, vector index and conversations.
      </p>

      {mutation.isError ? (
        <div className="mt-3">
          <ErrorState error={mutation.error} />
        </div>
      ) : null}

      {mutation.data && mutation.data.status === 'partially_cleaned' ? (
        <div className="mt-3 rounded border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-300">
          <p className="font-medium">Cleanup completed with some errors:</p>
          <ul className="mt-1 list-inside list-disc">
            {mutation.data.errors.map((err) => (
              <li key={err}>{err}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
          className="rounded bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </Dialog>
  )
}
