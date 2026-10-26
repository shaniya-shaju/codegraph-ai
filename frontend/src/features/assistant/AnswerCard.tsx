import type { QueryResponse } from '../../types/api'
import { StatusBadge, type BadgeTone } from '../../components/common/StatusBadge'
import { AnswerText, CitationList } from './CitationList'

const CONFIDENCE_TONE: Record<string, BadgeTone> = {
  HIGH: 'success',
  MEDIUM: 'info',
  LOW: 'warning',
  INSUFFICIENT_EVIDENCE: 'error',
}

/** See Prompt 11 "Answer Rendering": answer, confidence, limitations,
 * citations; confidence labels (never fake percentages); abstention
 * shown clearly with the backend's own explanation. */
export function AnswerCard({
  response,
  repositoryId,
  question,
}: {
  response: QueryResponse
  repositoryId: string
  question: string
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-4">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{question}</p>

      {response.abstained ? (
        <div className="rounded border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-200">
          <p className="font-medium">Insufficient repository evidence</p>
          <p className="mt-1 text-amber-300">{response.answer}</p>
        </div>
      ) : (
        <AnswerText text={response.answer} citations={response.citations} repositoryId={repositoryId} />
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <StatusBadge
          tone={CONFIDENCE_TONE[response.confidence_level] ?? 'neutral'}
          label={response.confidence_level.replace(/_/g, ' ')}
          title={response.confidence_reason}
        />
        <span className="text-xs text-slate-500">{response.confidence_reason}</span>
      </div>

      {response.limitations.length > 0 ? (
        <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs text-slate-500">
          {response.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      ) : null}

      {!response.abstained ? (
        <CitationList citations={response.citations} repositoryId={repositoryId} />
      ) : null}
    </div>
  )
}
