import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSourceSnippet } from '../../api/graph'
import { CodeBlock } from '../../components/code/CodeBlock'
import { ErrorState } from '../../components/common/ErrorState'
import { SkeletonRows } from '../../components/common/Skeleton'

export interface SourceTarget {
  repositoryId: string
  filePath: string
  startLine?: number | null
  endLine?: number | null
  qualifiedName?: string | null
}

interface SourceViewerContextValue {
  openSource: (target: SourceTarget) => void
}

const SourceViewerContext = createContext<SourceViewerContextValue | null>(null)

/** Global click-a-citation-to-view-source plumbing — see Prompt 11
 * "Source Code Viewer": "citation click -> open source panel/drawer ->
 * display file -> highlight cited lines." Mounted once near the app
 * root so any feature (assistant citations, graph node panel, impact
 * page) can open the same drawer via `useSourceViewer().openSource(...)`. */
export function SourceViewerProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<SourceTarget | null>(null)

  const openSource = useCallback((next: SourceTarget) => setTarget(next), [])
  const close = useCallback(() => setTarget(null), [])

  const value = useMemo(() => ({ openSource }), [openSource])

  return (
    <SourceViewerContext.Provider value={value}>
      {children}
      {target ? <SourceDrawer target={target} onClose={close} /> : null}
    </SourceViewerContext.Provider>
  )
}

export function useSourceViewer(): SourceViewerContextValue {
  const context = useContext(SourceViewerContext)
  if (!context) {
    throw new Error('useSourceViewer must be used within a SourceViewerProvider')
  }
  return context
}

function SourceDrawer({ target, onClose }: { target: SourceTarget; onClose: () => void }) {
  const query = useQuery({
    queryKey: [
      'source',
      target.repositoryId,
      target.filePath,
      target.startLine ?? null,
      target.endLine ?? null,
    ],
    queryFn: () =>
      getSourceSnippet(target.repositoryId, target.filePath, {
        startLine: target.startLine ?? undefined,
        endLine: target.endLine ?? undefined,
      }),
  })

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-xs">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Source: ${target.filePath}`}
        className="flex h-full w-full max-w-3xl flex-col border-l border-slate-800 bg-slate-950 text-slate-100 shadow-2xl"
      >
        <div className="flex items-start justify-between border-b border-slate-800 bg-slate-900/80 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-semibold text-slate-100">{target.filePath}</p>
            {target.qualifiedName ? (
              <p className="truncate text-xs text-slate-400">{target.qualifiedName}</p>
            ) : null}
            {target.startLine ? (
              <p className="text-xs text-slate-400">
                Lines {target.startLine}
                {target.endLine && target.endLine !== target.startLine ? `–${target.endLine}` : ''}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close source viewer"
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-auto bg-slate-950 p-4 text-slate-100">
          {query.isPending ? <SkeletonRows count={6} /> : null}
          {query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}
          {query.data ? (
            <div className="rounded-md border border-slate-800 bg-slate-900/90 p-3 text-slate-100 font-mono text-sm">
              <CodeBlock
                code={query.data.content}
                startLine={query.data.start_line}
                highlightStart={target.startLine}
                highlightEnd={target.endLine}
              />
            </div>
          ) : null}
          {query.data?.truncated ? (
            <p className="mt-2 text-xs text-slate-400">
              Showing lines {query.data.start_line}–{query.data.end_line} of{' '}
              {query.data.total_lines}.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}