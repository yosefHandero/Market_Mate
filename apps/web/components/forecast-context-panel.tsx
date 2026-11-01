import {
  confidenceScore,
  evidenceGrade,
  formatEstimatedExit,
  formatExpectedGrowthWindow,
  formatInvalidationLevel,
  formatProjectedRange,
  formatUpsideProbability,
  patternName,
  resolveExitWindow,
  riskLevel,
  topReasons,
} from '@/lib/decision-presentation';
import { forecastAnchor } from '@/lib/paper-contract';
import type { ScanResult } from '@/lib/types';

export function ForecastContextPanel({ results }: { results: ScanResult[] }) {
  const rows = results.filter((row) => row.decision_signal === 'BUY' && row.decision_role !== 'shadow');
  return (
    <section className="card" id="forecast-context" aria-label="Signal and advisory forecast context">
      <h2 className="proof-section-title">Signal and advisory forecast context</h2>
      <p className="muted small">
        The hybrid strategy keeps its existing candidate ranking: weekly upside probability,
        pattern samples, data quality and evidence provenance contribute alongside signal confidence.
        That ranking is not a one-hour profit probability. Signal confidence is the stored score;
        its learned calibration uses short-horizon signal-return evidence when available.
        Weekly probability describes a separate weekly forecast.
        Paper results come only from actual simulated fills and closes in the ledger.
      </p>
      <p className="muted small">
        Paper closure is time-based. All forecast ranges, stop and target levels below are advisory;
        no protective stop or target order is active.
      </p>
      {!rows.length ? <p className="muted">No saved BUY forecast context in this scan.</p> : rows.map((row) => {
        const window = resolveExitWindow(row);
        const weekly = row.weekly_prediction;
        const reasons = topReasons(row);
        return (
          <details key={`${row.asset_type}:${row.ticker}`} id={forecastAnchor(row.ticker)} className="ui-disclosure" open={rows.length === 1}>
            <summary className="ui-disclosure-summary">{row.ticker} · Signal confidence {confidenceScore(row)}/100 · Weekly context</summary>
            <div className="small" style={{ padding: '8px 0' }}>
              <p>Pattern: {patternName(row)} · Evidence {evidenceGrade(row)} · Risk {riskLevel(row)}</p>
              <p>Signal evidence horizon: {row.layer_details?.confidence?.blend?.horizon ?? row.strategy_primary_horizon ?? 'unavailable'}.</p>
              {reasons.length ? <ul className="decision-reason-list">{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}
              <p>Weekly upside probability (advisory): {formatUpsideProbability(row)}. This is separate from signal confidence and paper P/L.</p>
              {weekly ? <p>Weekly bias: {weekly.directional_bias}; samples {weekly.sample_size}; historical pattern hit rate {weekly.historical_hit_rate_pct == null ? 'unavailable' : `${weekly.historical_hit_rate_pct}%`} (not an upside probability).</p> : null}
              <p>Advisory forecast: {formatExpectedGrowthWindow(window)}</p>
              <p>Advisory target: {formatEstimatedExit(window)}</p>
              <p>{weekly ? 'Advisory weekly context' : 'Advisory forecast context'}: {formatProjectedRange(window)}</p>
              <p>Advisory stop: {formatInvalidationLevel(window)}</p>
              {row.price_prediction ? <p>Advisory structural range ({row.price_prediction.horizon_label}): ${row.price_prediction.range_low.toFixed(2)} – ${row.price_prediction.range_high.toFixed(2)}. {row.price_prediction.invalidation}</p> : null}
              {window?.stop_growing_signal ? <p>{window.stop_growing_signal}</p> : null}
              {window?.stop_growing_conditions?.length ? <ul className="decision-reason-list">{window.stop_growing_conditions.map((condition) => <li key={condition}>{condition}</li>)}</ul> : null}
              {window?.risk_warning ? <p>{window.risk_warning}</p> : null}
              {window?.confidence_change_note ? <p>{window.confidence_change_note}</p> : null}
            </div>
          </details>
        );
      })}
    </section>
  );
}
