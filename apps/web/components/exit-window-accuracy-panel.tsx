import type { ExitWindowAccuracyMetrics } from '@/lib/types';

function formatPercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatRate(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(1)}%`;
}

export function ExitWindowAccuracyPanel({
  metrics,
}: {
  metrics: ExitWindowAccuracyMetrics | null | undefined;
}) {
  if (!metrics) {
    return (
      <section className="card proof-placeholder-card" aria-label="Exit-window proof">
        <h2 className="proof-section-title">Exit-window proof</h2>
        <p className="muted" data-testid="exit-window-placeholder">
          Exit-window accuracy unavailable.
        </p>
      </section>
    );
  }

  const hasEvaluated = metrics.evaluated_count > 0;

  return (
    <section className="card" aria-label="Exit-window proof">
      <h2 className="proof-section-title">Exit-window proof</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Whether the stop-growing / exit-window prediction protected gains better than holding to
        the 1-week horizon (conservative same-bar rule).
      </p>
      {metrics.note ? (
        <p className="muted small" data-testid="exit-window-note">
          {metrics.note}
        </p>
      ) : null}

      <div className="proof-summary-grid">
        <div>
          <span className="muted small">Evaluated</span>
          <strong data-testid="exit-window-evaluated-count">{metrics.evaluated_count}</strong>
        </div>
        <div>
          <span className="muted small">Pending</span>
          <strong>{metrics.pending_count}</strong>
        </div>
        <div>
          <span className="muted small">Helped</span>
          <strong data-testid="exit-window-helped-rate">
            {hasEvaluated ? formatRate(metrics.helped_rate_pct) : '--'}
          </strong>
        </div>
        <div>
          <span className="muted small">Helped count</span>
          <strong>{metrics.helped_count}</strong>
        </div>
      </div>

      {metrics.by_asset_type.length ? (
        <div className="proof-table-wrap" style={{ marginTop: '0.75rem' }}>
          <table className="proof-table" data-testid="exit-window-by-asset-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>N</th>
                <th>Helped%</th>
                <th>Protected</th>
                <th>Hold</th>
                <th>Protected (stressed)</th>
              </tr>
            </thead>
            <tbody>
              {metrics.by_asset_type.map((row) => (
                <tr key={row.asset_type}>
                  <td>{row.asset_type}</td>
                  <td>{row.evaluated_count}</td>
                  <td>{formatRate(row.helped_rate_pct)}</td>
                  <td>{formatPercent(row.avg_protected_return_pct)}</td>
                  <td>{formatPercent(row.avg_hold_return_pct)}</td>
                  <td>{formatPercent(row.avg_protected_after_friction_stressed_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
