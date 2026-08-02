import type { ProofSummary } from '@/lib/types';

function formatCurrency(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPercent(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(2)}%`;
}

export function ProofSummaryPanel({ summary }: { summary: ProofSummary | null }) {
  if (!summary) {
    return (
      <section className="card proof-summary-panel" aria-label="Paper loop proof summary">
        <h2 className="proof-section-title">Paper loop proof</h2>
        <p className="muted">Proof summary unavailable.</p>
      </section>
    );
  }

  const { ledger, loop_metrics: loop } = summary;

  return (
    <section className="card proof-summary-panel" aria-label="Paper loop proof summary">
      <h2 className="proof-section-title">Paper loop proof</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Dry-run trades, ledger P&amp;L, and audit activity. Scan fresh:{' '}
        {summary.scan_fresh == null ? 'unknown' : summary.scan_fresh ? 'yes' : 'no'}.
      </p>
      {summary.note ? (
        <p className="muted small" data-testid="proof-summary-note">
          {summary.note}
        </p>
      ) : null}

      <div className="proof-summary-grid">
        <div>
          <span className="muted small">Realized P/L</span>
          <strong>{formatCurrency(ledger.total_realized_pnl)}</strong>
        </div>
        <div>
          <span className="muted small">Unrealized P/L</span>
          <strong data-testid="proof-unrealized-pnl">
            {formatCurrency(ledger.total_unrealized_pnl ?? null)}
          </strong>
        </div>
        <div>
          <span className="muted small">Win rate</span>
          <strong>{formatPercent(ledger.win_rate_pct)}</strong>
        </div>
        <div>
          <span className="muted small">Max drawdown</span>
          <strong>{formatCurrency(ledger.max_drawdown_usd)}</strong>
        </div>
        <div>
          <span className="muted small">Dry runs</span>
          <strong>{loop.recent_dry_runs}</strong>
        </div>
        <div>
          <span className="muted small">Previews</span>
          <strong>{loop.recent_previewed}</strong>
        </div>
        <div>
          <span className="muted small">Blocked</span>
          <strong>{loop.recent_blocked}</strong>
        </div>
        <div>
          <span className="muted small">Open positions</span>
          <strong>{ledger.open_positions}</strong>
        </div>
      </div>
    </section>
  );
}
