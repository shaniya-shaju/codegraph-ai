import { useNavigate } from 'react-router-dom'
import type { ImpactTarget } from '../../types/api'
import { useSourceViewer } from '../source/SourceViewerContext'

/** See Prompt 11 "Impact Header": target identity plus View Source / Ask
 * Assistant / Open in Graph actions. */
export function ImpactHeader({
  repositoryId,
  target,
}: {
  repositoryId: string
  target: ImpactTarget
}) {
  const navigate = useNavigate()
  const { openSource } = useSourceViewer()

  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
            {target.target_type}
          </span>
          <h1 className="mt-1 truncate font-mono text-lg text-slate-100">
            {target.qualified_name ?? target.name}
          </h1>
          {target.file_path ? (
            <p className="mt-0.5 text-xs text-slate-500">
              {target.file_path}
              {target.start_line ? `:${target.start_line}-${target.end_line}` : ''}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {target.file_path ? (
            <ActionButton
              label="View Source"
              onClick={() =>
                openSource({
                  repositoryId,
                  filePath: target.file_path as string,
                  startLine: target.start_line,
                  endLine: target.end_line,
                  qualifiedName: target.qualified_name,
                })
              }
            />
          ) : null}
          <ActionButton
            label="Ask Assistant"
            onClick={() =>
              navigate(`/repositories/${repositoryId}/assistant`, {
                state: { prefill: `Explain the impact of changing ${target.qualified_name ?? target.name}` },
              })
            }
          />
          <ActionButton
            label="Open in Graph"
            onClick={() =>
              navigate(`/repositories/${repositoryId}/graph`, {
                state: { rootSymbolId: target.symbol_id },
              })
            }
          />
        </div>
      </div>
    </div>
  )
}

function ActionButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
    >
      {label}
    </button>
  )
}
