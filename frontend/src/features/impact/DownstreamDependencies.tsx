import type { ImpactedSymbol } from '../../types/api'
import { useSourceViewer } from '../source/SourceViewerContext'

/** See Prompt 11 "Downstream Dependencies": what the target calls/relies
 * on — kept in a separate section from upstream callers, with an
 * explicit explanation that these are not necessarily affected by the
 * change (the target depends on them, not the other way around). */
export function DownstreamDependencies({
  repositoryId,
  dependencies,
}: {
  repositoryId: string
  dependencies: ImpactedSymbol[]
}) {
  const { openSource } = useSourceViewer()

  return (
    <div>
      <p className="mb-2 text-xs text-slate-500">
        Symbols this target depends on. These are not necessarily affected callers — they are
        shown for context on what this symbol relies on, not what relies on it.
      </p>
      {dependencies.length === 0 ? (
        <p className="text-xs text-slate-500">No known downstream dependencies.</p>
      ) : (
        <ul className="space-y-1.5">
          {dependencies.map((symbol) => (
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
