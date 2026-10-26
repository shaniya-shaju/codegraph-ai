import { useMutation } from '@tanstack/react-query'
import { explainImpact } from '../../api/impact'
import { ErrorState } from '../../components/common/ErrorState'

/** See Prompt 11 "Natural-Language Impact Explanation": a clearly
 * labeled "AI Explanation" that is never blended into the deterministic
 * impact table — it is an opt-in, separately-rendered narrative on top
 * of the same backend-computed result. */
export function ImpactExplanation({
  repositoryId,
  symbolId,
}: {
  repositoryId: string
  symbolId: string
}) {
  const mutation = useMutation({
    mutationFn: () => explainImpact(repositoryId, symbolId),
  })

  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-100">AI Explanation</h2>
        {!mutation.data ? (
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {mutation.isPending ? 'Generating…' : 'Explain this impact'}
          </button>
        ) : null}
      </div>

      {mutation.isError ? <ErrorState error={mutation.error} onRetry={() => mutation.mutate()} /> : null}

      {mutation.data ? (
        <div className="mt-3 space-y-3">
          <p className="rounded border border-sky-900 bg-sky-950/20 p-3 text-sm leading-relaxed text-slate-200">
            {mutation.data.explanation}
          </p>
          {mutation.data.warnings.length > 0 ? (
            <ul className="space-y-1 text-xs text-amber-300">
              {mutation.data.warnings.map((warning) => (
                <li key={warning}>⚠ {warning}</li>
              ))}
            </ul>
          ) : null}
          <p className="text-xs text-slate-500">
            Generated from the deterministic impact analysis above — it does not add any facts
            beyond what is shown in the tables on this page.
          </p>
        </div>
      ) : null}
    </div>
  )
}
