import { useNavigate } from 'react-router-dom'
import type { GraphNode } from '../../types/api'
import { useSourceViewer } from '../source/SourceViewerContext'

const IMPACT_ELIGIBLE_LABELS = new Set(['Function', 'Method', 'Class', 'APIEndpoint'])

/** See Prompt 11 "Graph Node Selection": name, qualified name, type,
 * file/line, signature (where available); only the actions that are
 * valid for that node type. This also doubles as the graph's textual
 * selected-node panel — see "Accessibility": "Graph canvas should
 * provide a textual selected-node panel because the graph itself is not
 * fully accessible." */
export function NodeDetailPanel({
  node,
  repositoryId,
  onShowCallers,
  onShowCallees,
  onShowDependencies,
}: {
  node: GraphNode
  repositoryId: string
  onShowCallers: () => void
  onShowCallees: () => void
  onShowDependencies: () => void
}) {
  const navigate = useNavigate()
  const { openSource } = useSourceViewer()
  const canCallExplore = node.label === 'Function' || node.label === 'Method'
  const canImpact = IMPACT_ELIGIBLE_LABELS.has(node.label)
  const signature = node.properties['signature']

  return (
    <div className="space-y-3 rounded border border-slate-800 bg-slate-900 p-4">
      <div>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
          {node.label}
        </span>
        <h3 className="mt-1 break-words font-mono text-sm text-slate-100">
          {node.qualified_name ?? node.name}
        </h3>
        {node.file_path ? (
          <p className="mt-0.5 text-xs text-slate-500">
            {node.file_path}
            {node.start_line ? `:${node.start_line}-${node.end_line}` : ''}
          </p>
        ) : null}
        {typeof signature === 'string' ? (
          <p className="mt-1 break-words font-mono text-xs text-slate-400">{signature}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        {node.file_path ? (
          <ActionButton
            label="View Source"
            onClick={() =>
              openSource({
                repositoryId,
                filePath: node.file_path as string,
                startLine: node.start_line,
                endLine: node.end_line,
                qualifiedName: node.qualified_name,
              })
            }
          />
        ) : null}
        {canCallExplore ? <ActionButton label="Show Callers" onClick={onShowCallers} /> : null}
        {canCallExplore ? <ActionButton label="Show Callees" onClick={onShowCallees} /> : null}
        <ActionButton label="Show Dependencies" onClick={onShowDependencies} />
        {canImpact ? (
          <ActionButton
            label="Analyze Impact"
            onClick={() => navigate(`/repositories/${repositoryId}/impact/${node.id}`)}
          />
        ) : null}
        <ActionButton
          label="Ask Assistant About This"
          onClick={() =>
            navigate(`/repositories/${repositoryId}/assistant`, {
              state: { prefill: `Explain ${node.qualified_name ?? node.name}` },
            })
          }
        />
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
