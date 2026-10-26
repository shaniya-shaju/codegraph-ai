import type { ImpactedSymbol } from '../../types/api'
import { useSourceViewer } from '../source/SourceViewerContext'

/** See Prompt 11 "Upstream Dependents": callers/dependents of the target
 * — code that would need to change or be re-verified if the target
 * changes. Direct callers and transitive dependents are kept visually
 * distinct, and this is a separate section from downstream dependencies
 * (which the target calls, not what calls the target). */
export function UpstreamDependents({
  repositoryId,
  directCallers,
  transitiveDependents,
}: {
  repositoryId: string
  directCallers: ImpactedSymbol[]
  transitiveDependents: ImpactedSymbol[]
}) {
  if (directCallers.length === 0 && transitiveDependents.length === 0) {
    return <p className="text-xs text-slate-500">No known callers or dependents.</p>
  }

  return (
    <div className="space-y-4">
      <SymbolGroup
        title="Direct callers"
        repositoryId={repositoryId}
        symbols={directCallers}
        emptyText="No direct callers."
      />
      <SymbolGroup
        title="Transitive dependents"
        repositoryId={repositoryId}
        symbols={transitiveDependents}
        emptyText="No transitive dependents."
      />
    </div>
  )
}

function SymbolGroup({
  title,
  repositoryId,
  symbols,
  emptyText,
}: {
  title: string
  repositoryId: string
  symbols: ImpactedSymbol[]
  emptyText: string
}) {
  const { openSource } = useSourceViewer()

  return (
    <div>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
        {title} ({symbols.length})
      </p>
      {symbols.length === 0 ? (
        <p className="text-xs text-slate-500">{emptyText}</p>
      ) : (
        <ul className="space-y-1.5">
          {symbols.map((symbol) => (
            <li
              key={symbol.symbol_id}
              className="rounded border border-slate-800 bg-slate-900 p-3 text-sm"
            >
              <div className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  className="truncate font-mono text-slate-200 hover:underline disabled:cursor-default disabled:no-underline"
                  disabled={!symbol.file_path}
                  onClick={() =>
                    symbol.file_path &&
                    openSource({
                      repositoryId,
                      filePath: symbol.file_path,
                      startLine: symbol.start_line,
                      endLine: symbol.end_line,
                      qualifiedName: symbol.qualified_name,
                    })
                  }
                >
                  {symbol.qualified_name ?? symbol.symbol_id}
                </button>
                <span className="shrink-0 text-xs text-slate-500">distance {symbol.distance}</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{symbol.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
