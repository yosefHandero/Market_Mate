'use client';

import { isHealthyFreshnessFlag } from '@/lib/freshness';
import { PAPER_READY_MIN_SCORE } from '@/lib/readiness';
import type { ScanResult } from '@/lib/types';

function storedReadinessLabel(row: ScanResult): string {
  return typeof row.readiness_score === 'number' && Number.isFinite(row.readiness_score)
    ? `${row.readiness_score}/100`
    : 'unknown';
}

/** Explains persisted BUY gate facts. It does not authorize a paper order. */
export function BuyGateDiagnostics({ results }: { results: ScanResult[] }) {
  const buys = results.filter((row) => row.decision_signal === 'BUY' && row.decision_role !== 'shadow');
  if (!buys.length) return null;

  return (
    <div aria-label="BUY gate diagnostics" className="small">
      <p className="muted">Detected BUY does not authorize a dry-run. Saved scan gate checks and saved safety state:</p>
      {buys.map((row) => {
        const checks = row.gate_checks ?? [];
        const failedChecks = checks.filter((check) => !check.passed);
        const passedChecks = checks.filter((check) => check.passed);
        const sampleCheck = checks.find((check) => check.name === 'sample_size');
        const performanceFailed = failedChecks.some((check) =>
          ['win_rate', 'avg_return', 'score_band_win_rate', 'score_band_avg_return'].includes(check.name),
        );
        const action = row.recommended_action ?? 'unknown';
        const eligibility = row.execution_eligibility ?? 'unknown';
        const actionAllowsPaper = row.recommended_action === 'preview' || row.recommended_action === 'dry_run';
        const storedAllowsPaper = actionAllowsPaper && row.gate_passed === true && row.execution_eligibility === 'eligible';
        const knownBlock = (
          (row.recommended_action != null && !actionAllowsPaper)
          || row.gate_passed === false
          || (row.execution_eligibility != null && row.execution_eligibility !== 'eligible')
          || failedChecks.length > 0
        );
        const heading = storedAllowsPaper
          ? 'Stored checks allow preview or dry-run'
          : knownBlock
            ? 'Paper action blocked'
            : 'Paper eligibility unknown';
        const qualityFlags = Object.entries(row.freshness_flags ?? {})
          .filter(([, value]) => !isHealthyFreshnessFlag(value))
          .map(([name, value]) => `${name.replaceAll('_', ' ')}: ${value}`);
        return (
          <div key={`${row.asset_type}:${row.ticker}`}>
            <strong>{row.ticker} — {heading}</strong>
            {sampleCheck?.passed === false ? (
              <p>Insufficient signal-return samples. The sample-count requirement is not met; performance checks also apply.</p>
            ) : sampleCheck?.passed === true && performanceFailed ? (
              <p>Sample-count check passed; measured performance failed the saved win-rate or average-return thresholds.</p>
            ) : null}
            {checks.length ? (
              failedChecks.length ? (
                <ul className="decision-reason-list">
                  {failedChecks.map((check) => <li key={check.name}>{check.detail}</li>)}
                </ul>
              ) : (
                <p>Saved evidence gate passed.</p>
              )
            ) : (
              <p>{row.gate_reason || 'Evidence gate results unavailable; approval is required.'}</p>
            )}
            {checks.length ? (
              <p className="muted">{passedChecks.length} of {checks.length} saved evidence checks passed.</p>
            ) : null}
            <p className="muted">
              Readiness {storedReadinessLabel(row)}; need {PAPER_READY_MIN_SCORE}. Action {action};
              {' '}need preview or dry_run. Eligibility {eligibility}.
              {' '}{row.is_top_pick ? 'Selected for Decision.' : 'Not selected for Decision.'}
            </p>
            {qualityFlags.length || row.provider_status ? (
              <p className="muted">
                Data quality — provider {row.provider_status ?? 'unknown'}
                {qualityFlags.length ? `; ${qualityFlags.join('; ')}` : ''}.
                {' '}Flagged inputs stay separate from bar age and still restrict paper action when the saved gate says so.
              </p>
            ) : null}
            {row.readiness_hard_stop && row.readiness_reason ? <p className="warning">{row.readiness_reason}</p> : null}
          </div>
        );
      })}
      <p className="muted">BUY gate checks use signal-return outcomes, separate from prediction-snapshot progress. These are saved scan checks, not a live recomputation. More resolved rows or elapsed time do not guarantee qualification: sample count, win rate and average return must all pass. Preview rechecks signal age, evidence and order limits.</p>
    </div>
  );
}
