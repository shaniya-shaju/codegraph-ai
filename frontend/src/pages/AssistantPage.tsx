import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { askQuestion } from '../api/query'
import { ErrorState } from '../components/common/ErrorState'
import { useDependencyStatus } from '../hooks/useDependencyStatus'
import { AnswerCard } from '../features/assistant/AnswerCard'
import { SuggestedQuestions } from '../features/assistant/SuggestedQuestions'
import type { QueryResponse } from '../types/api'

interface Turn {
  id: string
  question: string
  response?: QueryResponse
}

export function AssistantPage() {
  const { repositoryId } = useParams<{ repositoryId: string }>()
  const location = useLocation()
  const [input, setInput] = useState(
    () => (location.state as { prefill?: string } | null)?.prefill ?? '',
  )
  const [turns, setTurns] = useState<Turn[]>([])
  const conversationIdRef = useRef<string | null>(null)
  const { data: readiness } = useDependencyStatus()

  useEffect(() => {
    if ((location.state as { prefill?: string } | null)?.prefill) {
      window.history.replaceState({}, '')
    }
  }, [])

  const askMutation = useMutation({
    mutationFn: (question: string) =>
      askQuestion(repositoryId as string, question, 'hybrid', conversationIdRef.current),
    onSuccess: (response, question) => {
      if (!conversationIdRef.current) {
        conversationIdRef.current =
          typeof crypto !== 'undefined' && 'randomUUID' in crypto
            ? crypto.randomUUID()
            : `conv-${Date.now()}`
      }
      setTurns((prev) => [...prev, { id: `${Date.now()}`, question, response }])
    },
  })

  function submit(question: string) {
    const trimmed = question.trim()
    if (!trimmed || !repositoryId) return
    setInput('')
    askMutation.mutate(trimmed)
  }

  const graphUnavailable = readiness?.dependencies.neo4j?.status === 'UNAVAILABLE'
  const vectorUnavailable = readiness?.dependencies.chroma?.status === 'UNAVAILABLE'

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <div className="mb-3 flex items-center justify-between">
        {/* Visible Title in both Light & Dark modes */}
        <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">
          Code Assistant
        </h1>
      </div>

      {graphUnavailable ? (
        <p className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          Knowledge graph unavailable. Semantic code search remains available.
        </p>
      ) : null}
      {vectorUnavailable ? (
        <p className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          Semantic retrieval unavailable. Graph exploration may still work.
        </p>
      ) : null}

      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {turns.length === 0 && !askMutation.isPending ? (
          <SuggestedQuestions onSelect={submit} />
        ) : null}

        {turns.map((turn) => (
          <div key={turn.id}>
            {turn.response ? (
              <AnswerCard
                response={turn.response}
                repositoryId={repositoryId as string}
                question={turn.question}
              />
            ) : null}
          </div>
        ))}

        {askMutation.isPending ? (
          <div
            className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
            role="status"
          >
            <span className="h-2 w-2 animate-pulse rounded-full bg-sky-500" aria-hidden="true" />
            Thinking…
          </div>
        ) : null}

        {askMutation.isError ? <ErrorState error={askMutation.error} /> : null}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit(input)
        }}
        className="flex gap-2 border-t border-slate-200 pt-3 dark:border-slate-800"
      >
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about this repository…"
          aria-label="Ask about this repository"
          className="flex-1 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500"
        />
        <button
          type="submit"
          disabled={askMutation.isPending || !input.trim()}
          className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Ask
        </button>
      </form>
    </div>
  )
}