'use client';

import type { PaperLedgerSummary, PaperPositionSummary } from '@/lib/types';

function formatCurrency(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatQuantity(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

function formatTimestamp(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '--';
}

function priceKey(position: PaperPositionSummary) {
  return `${position.asset_type.toUpperCase()}:${position.ticker}`;
}

function estimateUnrealizedPnl(
  position: PaperPositionSummary,
  latestPrices: Record<string, number>,
): number | null {
  if (position.status !== 'open') {
    return null;
  }

  const latestPrice = latestPrices[priceKey(position)] ?? latestPrices[position.ticker];
  if (!latestPrice || !Number.isFinite(latestPrice)) {
    return null;
  }

  const sideMultiplier = position.side === 'buy' ? 1 : -1;
  return (latestPrice - position.simulated_fill_price) * position.quantity * sideMultiplier;
}

function PositionTable({
  title,
  positions,
  latestPrices,
  emptyMessage,
  highlightAuditId,
}: {
  title: string;
  positions: PaperPositionSummary[];
  latestPrices: Record<string, number>;
  emptyMessage: string;
  highlightAuditId?: number | null;
}) {
  return (
    <section style={{ display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: '1rem' }}>{title}</h3>
      {positions.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Action</th>
                <th>Qty</th>
                <th>Fill</th>
                <th>Notional</th>
                <th>P/L</th>
                <th>Audit</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => {
                const unrealized = estimateUnrealizedPnl(position, latestPrices);
                const pnl = position.status === 'closed' ? position.realized_pnl : unrealized;
                const highlighted =
                  highlightAuditId != null && position.execution_audit_id === highlightAuditId;
                return (
                  <tr
                    key={position.id}
                    className={highlighted ? 'highlighted-row' : undefined}
                    data-highlight={highlighted ? 'true' : undefined}
                  >
                    <td>
                      <strong>{position.ticker}</strong>
                      <div className="muted small">
                        {position.strategy_version ?? '--'}
                        {position.confidence != null ? ` | confidence ${position.confidence}` : ''}
                      </div>
                    </td>
                    <td>{position.side}</td>
                    <td>{formatQuantity(position.quantity)}</td>
                    <td>{formatCurrency(position.simulated_fill_price)}</td>
                    <td>{formatCurrency(position.notional_usd)}</td>
                    <td className={pnl == null ? 'muted' : pnl >= 0 ? 'positive' : 'negative'}>
                      {pnl == null ? 'unsupported' : formatCurrency(pnl)}
                    </td>
                    <td>{position.execution_audit_id ? `#${position.execution_audit_id}` : '--'}</td>
                    <td>
                      <span className="muted small">{formatTimestamp(position.opened_at)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          {emptyMessage}
        </p>
      )}
    </section>
  );
}

export function PaperLedgerPanel({
  positions,
  summary,
  errorMessage,
  latestPrices,
  highlightAuditId,
  refreshing,
  onRefresh,
}: {
  positions: PaperPositionSummary[];
  summary: PaperLedgerSummary | null;
  errorMessage?: string | null;
  latestPrices: Record<string, number>;
  highlightAuditId?: number | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const openPositions = positions.filter((position) => position.status === 'open');
  const closedPositions = positions.filter((position) => position.status === 'closed');
  const estimatedUnrealized = openPositions.reduce((sum, position) => {
    const pnl = estimateUnrealizedPnl(position, latestPrices);
    return pnl == null ? sum : sum + pnl;
  }, 0);

  return (
    <section id="paper-ledger" className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ marginBottom: 8 }}>Paper Ledger</h2>
          <p className="muted" style={{ margin: 0 }}>
            Dry-run positions and outcomes from the scanner execution audit trail.
          </p>
        </div>
        <button
          type="button"
          className="button"
          onClick={onRefresh}
          disabled={refreshing}
          style={{ width: 'auto', padding: '8px 14px', alignSelf: 'start' }}
        >
          {refreshing ? 'Refreshing...' : 'Refresh ledger'}
        </button>
      </div>

      {errorMessage ? (
        <p className="negative small" style={{ marginTop: 12 }}>
          {errorMessage}
        </p>
      ) : null}

      <div className="detail-panel small" style={{ marginTop: 16 }}>
        <div>
          <span className="muted">Total trades:</span>{' '}
          {summary?.total_count ?? positions.length}
        </div>
        <div>
          <span className="muted">Win rate:</span>{' '}
          {summary?.win_rate_pct == null ? '--' : `${summary.win_rate_pct.toFixed(2)}%`}
        </div>
        <div>
          <span className="muted">Open positions:</span>{' '}
          {summary?.open_positions ?? openPositions.length}
        </div>
        <div>
          <span className="muted">Closed positions:</span>{' '}
          {summary?.closed_positions ?? closedPositions.length}
        </div>
        <div>
          <span className="muted">Total paper notional:</span>{' '}
          {formatCurrency(summary?.total_notional_usd ?? null)}
        </div>
        <div>
          <span className="muted">Realized P/L:</span>{' '}
          {formatCurrency(summary?.total_realized_pnl ?? null)}
        </div>
        <div>
          <span className="muted">Gross P/L:</span>{' '}
          {formatCurrency(summary?.gross_pnl_usd ?? null)}
        </div>
        <div>
          <span className="muted">Max drawdown:</span>{' '}
          {formatCurrency(summary?.max_drawdown_usd ?? null)}
        </div>
        <div>
          <span className="muted">Est. unrealized P/L:</span>{' '}
          {openPositions.length ? formatCurrency(estimatedUnrealized) : '--'}
        </div>
        <div>
          <span className="muted">Last opened:</span> {formatTimestamp(summary?.last_opened_at)}
        </div>
      </div>

      <div style={{ display: 'grid', gap: 18, marginTop: 18 }}>
        <PositionTable
          title="Open Paper Positions"
          positions={openPositions}
          latestPrices={latestPrices}
          emptyMessage="No open paper positions yet."
          highlightAuditId={highlightAuditId}
        />
        <PositionTable
          title="Closed Paper Positions"
          positions={closedPositions}
          latestPrices={latestPrices}
          emptyMessage="No closed paper positions yet."
          highlightAuditId={highlightAuditId}
        />
      </div>
    </section>
  );
}
