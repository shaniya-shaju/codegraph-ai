import { useState } from 'react'
import { useDependencyStatus } from '../../hooks/useDependencyStatus'
import { StatusBadge } from '../common/StatusBadge'

/** Compact global dependency indicator — see Prompt 11 "Readiness /
 * Dependency Banner". Clicking it expands a short, plain-language
 * explanation of what's degraded and what still works; never shows a
 * raw infrastructure exception. */
export function DependencyBanner() {
  const { data, isPending, isError } = useDependencyStatus()
  const [expanded, setExpanded] = useState(false)

  if (isPending) {
    return <span className="text-xs text-slate-500">Checking backend…</span>
  }

  if (isError || !data) {
    return <StatusBadge tone="error" label="Backend unavailable" />
  }

  const tone = data.status === 'ready' ? 'success' : data.status === 'degraded' ? 'warning' : 'error'
  const label =
    data.status === 'ready'
      ? 'All systems ready'
      : data.status === 'degraded'
        ? 'Degraded'
        : 'Backend unavailable'

  const neo4jDown = data.dependencies.neo4j?.status === 'UNAVAILABLE'
  const vectorDown = data.dependencies.chroma?.status === 'UNAVAILABLE'
  const embeddingDown = data.dependencies.embedding_provider?.status === 'UNAVAILABLE'
  const llm = data.dependencies.llm
  const llmDown = llm?.status === 'UNAVAILABLE' || llm?.status === 'NOT_LOADED'
  // The exact copy differs by provider — see Prompt 11.5 "Frontend setup
  // visibility" (LM Studio-specific instructions) vs "Provider-independent
  // UI" (never assume/imply a specific vendor when one isn't actually
  // configured). `llm.provider` comes straight from GET /health/ready.
  const llmIsLocal = llm?.provider === 'openai_compatible'

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="rounded"
      >
        <StatusBadge tone={tone} label={label} />
      </button>
      {expanded ? (
        <div
          role="status"
          className="absolute right-0 z-40 mt-2 w-80 space-y-2 rounded border border-slate-800 bg-slate-900 p-3 text-xs text-slate-300 shadow-lg"
        >
          {data.status === 'ready' ? <p>All dependencies are ready.</p> : null}
          {neo4jDown ? (
            <p>
              Knowledge graph unavailable. Semantic code search remains available. Graph
              exploration and impact analysis are temporarily unavailable.
            </p>
          ) : null}
          {vectorDown ? (
            <p>Semantic retrieval unavailable. Graph exploration may still work.</p>
          ) : null}
          {embeddingDown ? (
            <p>Embedding model unavailable. Semantic repository analysis cannot run.</p>
          ) : null}
          {llmDown && llmIsLocal ? (
            <p>
              Local AI model is not connected. Start the LM Studio local server and load the
              configured model — questions can still be searched, but answers won't be generated.
            </p>
          ) : null}
          {llmDown && !llmIsLocal ? (
            <p>
              AI assistant is not configured. Set a valid LLM API key to enable answer generation
              — questions can still be searched.
            </p>
          ) : null}
          <ul className="space-y-1">
            {Object.entries(data.dependencies).map(([name, state]) => (
              <li key={name} className="flex items-center justify-between gap-2">
                <span className="capitalize">{name.replace(/_/g, ' ')}</span>
                <StatusBadge
                  tone={
                    state.status === 'READY'
                      ? 'success'
                      : state.status === 'NOT_LOADED'
                        ? 'neutral'
                        : 'error'
                  }
                  label={state.status}
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
