'use client';

import { FRESH_BAR_MAX_MINUTES, isHealthyFreshnessFlag } from '@/lib/freshness';
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
        const savedChecks = row.gate_checks ?? [];
        const evidenceSources = savedChecks.find((check) => check.name === 'evidence_sources');
        const checks = savedChecks.filter((check) => check.name !== 'evidence_sources');
        const failedChecks = checks.filter((check) => !check.passed);
        const passedChecks = checks.filter((check) => check.passed);
        const sampleCheck = checks.find((check) => check.name === 'sample_size');
        const performanceFailed = failedChecks.some((check) =>
          ['win_rate', 'avg_return', 'score_band_win_rate', 'score_band_avg_return'].includes(check.name),
        );
        const action = row.recommended_action ?? 'unknown';
        const eligibility = row.execution_eligibility ?? 'unknown';
        const actionAllowsPaper = row.recommended_action === 'preview' || row.recommended_action === 'dry_run';
        const qualityFlags = Object.entries(row.freshness_flags ?? {})
          .filter(([, value]) => !isHealthyFreshnessFlag(value))
          .map(([name, value]) => `${name.replaceAll('_', ' ')}: ${value}`);
        const dataBlocked = qualityFlags.length > 0 || ['critical', 'error'].includes(row.provider_status?.trim().toLowerCase())
          || (row.bar_age_minutes ?? 0) > FRESH_BAR_MAX_MINUTES;
        const knownBlock = (
          dataBlocked || row.readiness_hard_stop === true
          || (row.recommended_action != null && !actionAllowsPaper)
          || row.gate_passed === false
          || (row.execution_eligibility != null && row.execution_eligibility !== 'eligible')
          || failedChecks.length > 0
        );
        const storedAllowsPaper = !knownBlock && actionAllowsPaper && row.gate_passed === true && eligibility === 'eligible'
          && Number.isFinite(row.bar_age_minutes);
        const heading = storedAllowsPaper
          ? 'Stored checks allow preview or dry-run'
          : knownBlock
            ? 'Paper action blocked'
            : 'Paper eligibility unknown';
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
            {evidenceSources ? (
              <>
                <p className="muted">{evidenceSources.detail}</p>
                {passedChecks.length ? (
                  <details className="ui-disclosure">
                    <summary className="ui-disclosure-summary muted small">Passed evidence checks</summary>
                    <ul className="decision-reason-list">
                      {passedChecks.map((check) => <li key={check.name}>{check.detail}</li>)}
                    </ul>
                  </details>
                ) : null}
              </>
            ) : null}
            <p className="muted">
              Readiness {storedReadinessLabel(row)}; need {PAPER_READY_MIN_SCORE}. Action {action};
              {' '}need preview or dry_run. Eligibility {eligibility}.
              {' '}{row.is_top_pick ? 'Selected for Decision.' : 'Not selected for Decision.'}
            </p>
            {typeof row.bar_age_minutes === 'number' && Number.isFinite(row.bar_age_minutes) ? (
              <p className="muted">
                Bar age at scan {row.bar_age_minutes} minutes. Paper limit {FRESH_BAR_MAX_MINUTES} minutes.
              </p>
            ) : null}
            {qualityFlags.length || row.provider_status ? (
              <p className="muted">
                Data quality — provider {row.provider_status ?? 'unknown'}
                {qualityFlags.length ? `; ${qualityFlags.join('; ')}` : ''}.
                {' '}Paper requires healthy freshness flags and a provider status outside critical or error.
              </p>
            ) : null}
            {row.news_cache_label ? <p className="muted">News at scan · {row.news_cache_label}</p> : null}
            {row.provider_warnings?.includes('market_bars_market_closed') ? (
              <p className="muted">Stock bars were retrieved outside scheduled trading hours for that feed. The paper freshness limit still applies.</p>
            ) : null}
            {row.readiness_hard_stop && row.readiness_reason ? <p className="warning">{row.readiness_reason}</p> : null}
          </div>
        );
      })}
      <p className="muted">BUY gate checks use signal-return outcomes, separate from prediction-snapshot progress. These are saved scan checks, not a live recomputation. Historical supplements support paper eligibility only. More resolved rows or elapsed time do not guarantee qualification. Sample count, win rate and average return must all pass. Preview rechecks signal age, evidence and order limits.</p>
    </div>
  );
}
