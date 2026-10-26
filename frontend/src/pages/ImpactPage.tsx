import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getImpactAnalysis } from '../api/impact'
import { ErrorState } from '../components/common/ErrorState'
import { Skeleton } from '../components/common/Skeleton'
import { AffectedApis } from '../features/impact/AffectedApis'
import { AffectedFiles } from '../features/impact/AffectedFiles'
import { DownstreamDependencies } from '../features/impact/DownstreamDependencies'
import { ImpactExplanation } from '../features/impact/ImpactExplanation'
import { ImpactGraph } from '../features/impact/ImpactGraph'
import { ImpactHeader } from '../features/impact/ImpactHeader'
import { ImpactStatsCards } from '../features/impact/ImpactStatsCards'
import { RiskSummary } from '../features/impact/RiskSummary'
import { SignalBreakdown } from '../features/impact/SignalBreakdown'
import { UpstreamDependents } from '../features/impact/UpstreamDependents'
import { SymbolSearch } from '../features/symbols/SymbolSearch'
import { useDependencyStatus } from '../hooks/useDependencyStatus'

/** `/repositories/:repositoryId/impact/:symbolId?` — see Prompt 11
 * "Impact Analysis Page". Every number and label shown here comes
 * straight off `ImpactAnalysisResult` — this page composes and labels
 * backend output, it never recomputes risk or relationships itself. */
export function ImpactPage() {
  const { repositoryId, symbolId } = useParams<{ repositoryId: string; symbolId?: string }>()
  const navigate = useNavigate()
  const { data: readiness } = useDependencyStatus()
  const graphUnavailable = readiness?.dependencies.neo4j?.status === 'UNAVAILABLE'

  const impactQuery = useQuery({
    queryKey: ['impact', repositoryId, symbolId],
    queryFn: () => getImpactAnalysis(repositoryId as string, symbolId as string),
    // See GraphPage's identical guard: don't fire ahead of readiness
    // actually resolving, or a truly-down Neo4j reads as "available" for
    // one render.
    enabled: Boolean(repositoryId && symbolId) && readiness !== undefined && !graphUnavailable,
  })

  if (!repositoryId) {
    return <ErrorState error={new Error('Missing repository id.')} />
  }

  if (graphUnavailable) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold text-slate-100">Impact Analysis</h1>
        <div
          role="status"
          className="rounded border border-amber-900 bg-amber-950/30 px-4 py-3 text-sm text-amber-300"
        >
          Knowledge graph unavailable. Change-impact analysis requires the knowledge graph and is
          unavailable until Neo4j is reachable again.
        </div>
      </div>
    )
  }

  if (!symbolId) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold text-slate-100">Impact Analysis</h1>
        <p className="text-sm text-slate-400">
          Search for a function, method, class, or API endpoint to analyze the structural impact
          of changing it.
        </p>
        <div className="max-w-lg">
          <SymbolSearch
            repositoryId={repositoryId}
            onSelect={(result) => navigate(`/repositories/${repositoryId}/impact/${result.symbol_id}`)}
          />
        </div>
      </div>
    )
  }

  if (impactQuery.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (impactQuery.isError) {
    return <ErrorState error={impactQuery.error} onRetry={() => impactQuery.refetch()} />
  }

  const result = impactQuery.data
  if (!result) return null

  return (
    <div className="space-y-6 pb-8">
      <ImpactHeader repositoryId={repositoryId} target={result.target} />

      <RiskSummary riskScore={result.risk_score} riskLevel={result.risk_level} />

      <ImpactStatsCards result={result} />

      {result.truncated ? (
        <p className="rounded border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
          This analysis was truncated before covering the full dependency graph
          {result.diagnostics.truncated_reason ? `: ${result.diagnostics.truncated_reason}` : '.'}
        </p>
      ) : null}

      <Section title="Risk Signal Breakdown">
        <SignalBreakdown signals={result.risk_signals} />
      </Section>

      <Section title="Affected APIs">
        <AffectedApis endpoints={result.affected_endpoints} />
      </Section>

      <Section title="Affected Files">
        <AffectedFiles files={result.affected_files} />
      </Section>

      <Section title="Upstream Dependents">
        <UpstreamDependents
          repositoryId={repositoryId}
          directCallers={result.direct_callers}
          transitiveDependents={result.transitive_dependents}
        />
      </Section>

      <Section title="Downstream Dependencies">
        <DownstreamDependencies repositoryId={repositoryId} dependencies={result.downstream_dependencies} />
      </Section>

      <Section title="Impact Graph">
        <ImpactGraph result={result} />
      </Section>

      <ImpactExplanation repositoryId={repositoryId} symbolId={symbolId} />

      {result.limitations.length > 0 ? (
        <Section title="Limitations">
          <ul className="list-inside list-disc space-y-1 text-xs text-slate-400">
            {result.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold text-slate-100">{title}</h2>
      {children}
    </section>
  )
}
