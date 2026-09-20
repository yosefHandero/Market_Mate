import type { WalkForwardAssetMetrics, WalkForwardRunSummary } from '@/lib/types';

function formatPercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatRate(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(1)}%`;
}

/** Map walk-forward metric track strings onto shared evidence-contract labels. */
function trackLabel(track: string) {
  switch (track) {
    case 'holdout':
      return 'Walk-forward holdout';
    case 'validation':
      return 'Walk-forward research (validation)';
    case 'research':
      return 'Walk-forward research';
    default:
      return track;
  }
}

function groupLabel(row: WalkForwardAssetMetrics) {
  return `${row.asset_type} / ${trackLabel(row.track)}`;
}

export function WalkForwardProofPanel({
  summary,
}: {
  summary: WalkForwardRunSummary | null | undefined;
}) {
  if (!summary) {
    return (
      <section className="card proof-placeholder-card" aria-label="Historical walk-forward proof">
        <h2 className="proof-section-title">Historical walk-forward proof</h2>
        <p className="muted" data-testid="walk-forward-placeholder">
          No historical walk-forward proof run yet. Run the proof engine to populate this section.
        </p>
      </section>
    );
  }

  const verdict = summary.pilot_verdict;
  const rows = summary.by_asset_track ?? [];

  return (
    <section className="card" aria-label="Historical walk-forward proof">
      <h2 className="proof-section-title">Historical walk-forward proof</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Stands at past dates using only prior daily data, makes the same top {summary.top_n_per_asset}{' '}
        stock and top {summary.top_n_per_asset} crypto weekly predictions, and resolves them 1 week
        forward. Historical evidence only &mdash; kept separate from live-forward proof.
      </p>

      <div className="proof-summary-grid">
        <div>
          <span className="muted small">Replay window</span>
          <strong data-testid="walk-forward-window">
            {summary.target_years}y &middot; every {summary.step_days}d
          </strong>
        </div>
        <div>
          <span className="muted small">Predictions</span>
          <strong data-testid="walk-forward-prediction-count">{summary.prediction_count}</strong>
        </div>
        <div>
          <span className="muted small">Resolved</span>
          <strong>{summary.resolved_count}</strong>
        </div>
        <div>
          <span className="muted small">Symbols</span>
          <strong>{summary.symbol_count}</strong>
        </div>
      </div>

      <div
        className={`walk-forward-verdict ${verdict.ready ? 'positive' : 'muted'}`}
        data-testid="walk-forward-verdict"
        style={{ marginTop: '0.75rem' }}
      >
        <strong>
          Tiny-pilot review bar: {verdict.ready ? 'MET' : 'NOT MET'}
        </strong>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {verdict.summary}
        </p>
        <p className="negative small" data-testid="walk-forward-trust-note" style={{ marginBottom: 0 }}>
          Real-money trust remains blocked. Paper-only, dry-run, decision-support use only.
        </p>
      </div>

      {verdict.by_asset?.length ? (
        <div
          className="walk-forward-asset-verdicts"
          data-testid="walk-forward-asset-verdicts"
          style={{ marginTop: '0.75rem', display: 'flex', gap: 12, flexWrap: 'wrap' }}
        >
          {verdict.by_asset.map((asset) => (
            <div
              key={asset.asset_type}
              className={`badge ${asset.ready ? 'green' : ''}`}
              data-testid={`walk-forward-verdict-${asset.asset_type}`}
              title={asset.summary}
            >
              <span className="muted">{asset.asset_type}</span>{' '}
              <strong>{asset.ready ? 'MET' : 'NOT MET'}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {rows.length ? (
        <div className="proof-table-wrap" style={{ marginTop: '0.75rem' }}>
          <table className="proof-table" data-testid="walk-forward-metrics-table">
            <thead>
              <tr>
                <th>Asset / Track</th>
                <th>N</th>
                <th>Upside hit</th>
                <th>Avg ret</th>
                <th>After friction</th>
                <th>Calib gap</th>
                <th>Exit helped</th>
                <th>Worst decile</th>
                <th>Max DD</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={groupLabel(row)}>
                  <td>{groupLabel(row)}</td>
                  <td>{row.resolved_count}</td>
                  <td>{formatRate(row.upside_hit_rate_pct)}</td>
                  <td>{formatPercent(row.avg_return_pct)}</td>
                  <td>{formatPercent(row.avg_return_after_friction_stressed_pct)}</td>
                  <td>{formatRate(row.calibration_mean_abs_gap_pct)}</td>
                  <td>{formatRate(row.exit_window_helped_rate_pct)}</td>
                  <td>{formatPercent(row.worst_decile_mean_pct)}</td>
                  <td>{formatRate(row.max_drawdown_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted small" data-testid="walk-forward-empty">
          {summary.note ?? 'No resolved historical walk-forward predictions yet.'}
        </p>
      )}

      {verdict.checks?.length ? (
        <details style={{ marginTop: '0.75rem' }}>
          <summary className="muted small">Pilot-readiness checks</summary>
          <ul className="walk-forward-checks">
            {verdict.checks.map((check) => (
              <li key={check.name} className={check.passed ? 'positive small' : 'negative small'}>
                {check.passed ? 'PASS' : 'FAIL'} &mdash; {check.detail}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="walk-forward-manifest muted small" style={{ marginTop: '0.75rem' }} data-testid="walk-forward-manifest">
        <p style={{ margin: 0 }}>
          {summary.survivorship_caveat ??
            'Universe is the current watchlist only; results are survivorship-limited.'}
        </p>
        <p style={{ margin: '4px 0 0' }}>
          Run manifest: engine {summary.engine_version ?? 'n/a'} &middot; config{' '}
          {summary.config_fingerprint ? summary.config_fingerprint.slice(0, 12) : 'n/a'} &middot;{' '}
          ruler {summary.ruler_version ?? 'n/a'} /{' '}
          {summary.ruler_fingerprint ? summary.ruler_fingerprint.slice(0, 12) : 'n/a'} &middot;{' '}
          {summary.overlap_status ?? 'overlap n/a'} &middot; data quality{' '}
          {summary.data_quality_ok == null
            ? 'n/a'
            : summary.data_quality_ok
              ? 'ok'
              : `issues (${summary.data_quality_issues?.length ?? 0})`}
        </p>
      </div>
    </section>
  );
}
