import type { ConfidencePerformance } from '@/lib/types';

function formatPercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatRate(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(1)}%`;
}

export function ConfidencePerformancePanel({
  performance,
}: {
  performance: ConfidencePerformance | null | undefined;
}) {
  if (!performance) {
    return (
      <section className="card proof-placeholder-card" aria-label="Confidence proof">
        <h2 className="proof-section-title">Confidence proof</h2>
        <p className="muted" data-testid="confidence-performance-placeholder">
          Confidence ranking and calibration unavailable.
        </p>
      </section>
    );
  }

  const { ranking, calibration } = performance;
  const rankingBuckets = ranking.buckets.slice(0, 8);
  const calibrationBuckets = calibration.buckets.slice(0, 8);

  return (
    <section className="card" aria-label="Confidence proof">
      <h2 className="proof-section-title">Confidence proof</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Ranking: higher-confidence bands should outperform lower bands. Calibration: predicted
        upside probability vs realized up-rate.
      </p>

      {ranking.note ? (
        <p className="muted small" data-testid="confidence-ranking-note">
          {ranking.note}
        </p>
      ) : null}
      {ranking.monotonic_by_group != null ? (
        <p
          className={ranking.monotonic_by_group ? 'positive small' : 'negative small'}
          data-testid="confidence-ranking-verdict"
        >
          {ranking.monotonic_by_group
            ? 'Higher-confidence bands are not underperforming lower bands.'
            : 'At least one group shows higher-confidence underperformance.'}
        </p>
      ) : null}

      {rankingBuckets.length ? (
        <div className="proof-table-wrap" style={{ marginTop: '0.75rem' }}>
          <table className="proof-table" data-testid="confidence-ranking-table">
            <thead>
              <tr>
                <th>Band</th>
                <th>Asset</th>
                <th>Signal</th>
                <th>N</th>
                <th>Win%</th>
                <th>Avg</th>
                <th>After friction</th>
              </tr>
            </thead>
            <tbody>
              {rankingBuckets.map((bucket) => (
                <tr
                  key={`${bucket.asset_type}-${bucket.signal}-${bucket.sample_source}-${bucket.score_band}`}
                >
                  <td>{bucket.score_band}</td>
                  <td>{bucket.asset_type}</td>
                  <td>{bucket.signal}</td>
                  <td>{bucket.evaluated_count}</td>
                  <td>{formatRate(bucket.win_rate_pct)}</td>
                  <td>{formatPercent(bucket.avg_return_pct)}</td>
                  <td>{formatPercent(bucket.avg_return_after_friction_stressed_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {calibration.note ? (
        <p className="muted small" data-testid="confidence-calibration-note" style={{ marginTop: '1rem' }}>
          {calibration.note}
        </p>
      ) : null}
      {calibration.mean_abs_reliability_gap_pct != null ? (
        <p className="small" data-testid="confidence-calibration-gap">
          Mean absolute reliability gap: {formatRate(calibration.mean_abs_reliability_gap_pct)}
        </p>
      ) : null}

      {calibrationBuckets.length ? (
        <div className="proof-table-wrap" style={{ marginTop: '0.75rem' }}>
          <table className="proof-table" data-testid="confidence-calibration-table">
            <thead>
              <tr>
                <th>Predicted band</th>
                <th>Asset</th>
                <th>N</th>
                <th>Predicted</th>
                <th>Realized up</th>
                <th>Gap</th>
              </tr>
            </thead>
            <tbody>
              {calibrationBuckets.map((bucket) => (
                <tr key={`${bucket.asset_type}-${bucket.probability_band}`}>
                  <td>{bucket.probability_band}</td>
                  <td>{bucket.asset_type}</td>
                  <td>{bucket.evaluated_count}</td>
                  <td>{formatRate(bucket.avg_predicted_pct)}</td>
                  <td>{formatRate(bucket.realized_up_rate_pct)}</td>
                  <td>{formatRate(bucket.reliability_gap_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
