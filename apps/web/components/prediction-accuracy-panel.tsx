import type { PredictionAccuracyMetrics } from '@/lib/types';

function formatPercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(1)}%`;
}

export function PredictionAccuracyPanel({
  metrics,
}: {
  metrics: PredictionAccuracyMetrics | null | undefined;
}) {
  if (!metrics) {
    return (
      <section className="card proof-placeholder-card" aria-label="Prediction accuracy">
        <h2 className="proof-section-title">Prediction accuracy</h2>
        <p className="muted" data-testid="prediction-accuracy-placeholder">
          Accuracy summary unavailable.
        </p>
      </section>
    );
  }

  const hasEvaluated = metrics.evaluated_count > 0;

  return (
    <section className="card" aria-label="Prediction accuracy">
      <h2 className="proof-section-title">Prediction accuracy</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Tracks whether price at the structural horizon landed inside the predicted stop/target range.
      </p>
      {metrics.note ? (
        <p className="muted small" data-testid="prediction-accuracy-note">
          {metrics.note}
        </p>
      ) : null}

      <div className="proof-summary-grid">
        <div>
          <span className="muted small">Evaluated</span>
          <strong data-testid="prediction-evaluated-count">{metrics.evaluated_count}</strong>
        </div>
        <div>
          <span className="muted small">Pending</span>
          <strong>{metrics.pending_count}</strong>
        </div>
        <div>
          <span className="muted small">In range</span>
          <strong data-testid="prediction-in-range-rate">
            {hasEvaluated ? formatPercent(metrics.in_range_rate_pct) : '--'}
          </strong>
        </div>
        <div>
          <span className="muted small">Below range</span>
          <strong>{metrics.below_range_count}</strong>
        </div>
        <div>
          <span className="muted small">Above range</span>
          <strong>{metrics.above_range_count}</strong>
        </div>
        <div>
          <span className="muted small">Missed price</span>
          <strong>{metrics.missed_count}</strong>
        </div>
      </div>
    </section>
  );
}
