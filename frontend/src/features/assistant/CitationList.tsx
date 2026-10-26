import { useSourceViewer } from '../source/SourceViewerContext'
import type { CodeCitation } from '../../types/api'

/** See Prompt 11 "Citation Rendering": clickable citations that open the
 * source viewer with file path / line range / qualified symbol —
 * "Never create file/line citations from answer text manually. Use only
 * backend citation metadata." */
export function CitationList({
  citations,
  repositoryId,
}: {
  citations: CodeCitation[]
  repositoryId: string
}) {
  const { openSource } = useSourceViewer()

  if (citations.length === 0) return null

  return (
    <ol className="mt-3 space-y-1.5 border-t border-slate-800 pt-3">
      {citations.map((citation, index) => (
        <li key={citation.citation_id}>
          <button
            type="button"
            disabled={!citation.file_path}
            onClick={() =>
              citation.file_path &&
              openSource({
                repositoryId,
                filePath: citation.file_path,
                startLine: citation.start_line,
                endLine: citation.end_line,
                qualifiedName: citation.qualified_name,
              })
            }
            className="flex w-full items-start gap-2 rounded px-2 py-1 text-left text-xs hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="mt-0.5 shrink-0 rounded bg-slate-800 px-1.5 py-0.5 font-mono text-sky-400">
              [{index + 1}]
            </span>
            <span className="min-w-0">
              <span className="block truncate font-mono text-slate-300">
                {citation.file_path ?? 'unknown file'}
                {citation.start_line ? `:${citation.start_line}-${citation.end_line}` : ''}
              </span>
              {citation.qualified_name ? (
                <span className="block truncate text-slate-500">{citation.qualified_name}</span>
              ) : null}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}

/** Renders answer text with `[1]`, `[2]`, ... markers as clickable spans
 * — the backend has already validated/renumbered these against the
 * `citations` array (see app.rag.citation_validator), so this component
 * only ever links to a citation that's really in the list, never
 * constructs one from the raw text itself. */
export function AnswerText({
  text,
  citations,
  repositoryId,
}: {
  text: string
  citations: CodeCitation[]
  repositoryId: string
}) {
  const { openSource } = useSourceViewer()
  const parts = text.split(/(\[\d+\])/g)

  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
      {parts.map((part, index) => {
        const match = /^\[(\d+)\]$/.exec(part)
        if (!match) return <span key={index}>{part}</span>

        const citationIndex = Number(match[1]) - 1
        const citation = citations[citationIndex]
        if (!citation) return <span key={index}>{part}</span>

        return (
          <button
            key={index}
            type="button"
            disabled={!citation.file_path}
            onClick={() =>
              citation.file_path &&
              openSource({
                repositoryId,
                filePath: citation.file_path,
                startLine: citation.start_line,
                endLine: citation.end_line,
                qualifiedName: citation.qualified_name,
              })
            }
            className="mx-0.5 rounded bg-slate-800 px-1 font-mono text-sky-400 hover:bg-slate-700 disabled:cursor-not-allowed"
          >
            {part}
          </button>
        )
      })}
    </p>
  )
}
