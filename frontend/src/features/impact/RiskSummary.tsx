import type { RiskLevel } from '../../types/api'

const RISK_STYLE: Record<RiskLevel, string> = {
  LOW: 'bg-emerald-950/40 text-emerald-300 border-emerald-900',
  MEDIUM: 'bg-amber-950/40 text-amber-300 border-amber-900',
  HIGH: 'bg-orange-950/40 text-orange-300 border-orange-900',
  CRITICAL: 'bg-rose-950/40 text-rose-300 border-rose-900',
}

/** See Prompt 11 "Risk Score Visualization": label it "Structural
 * Change-Impact Risk", never "Failure Risk", and make clear via a
 * tooltip/caption that this is a structural signal, not a probability of
 * anything actually breaking. */
export function RiskSummary({
  riskScore,
  riskLevel,
}: {
  riskScore: number
  riskLevel: RiskLevel
}) {
  return (
    <div className={`rounded border p-4 ${RISK_STYLE[riskLevel]}`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide opacity-80">
            Structural Change-Impact Risk
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {riskLevel}
            <span className="ml-2 text-sm font-normal opacity-80">
              (score {riskScore.toFixed(2)})
            </span>
          </p>
        </div>
        <span
          title="This score summarizes structural signals — how many callers, files, and public APIs sit downstream of this symbol. It is not a probability that a change will actually break anything, and it does not account for test coverage or runtime behavior."
          aria-label="What this score means"
          className="cursor-help rounded-full border border-current px-2 py-0.5 text-xs opacity-80"
        >
          ?
        </span>
      </div>
      <p className="mt-2 text-xs opacity-80">
        A structural signal derived from graph connectivity — not a probability that this change
        will break anything.
      </p>
    </div>
  )
}
