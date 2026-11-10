'use client';

import { useState } from 'react';
import { reconcilePaperLedger } from '@/lib/api';
import { formatHoldingDuration, formatPaperTimestamp, formatUnitPrice } from '@/lib/paper-contract';
import type { PaperLedgerSummary, PaperPositionSummary } from '@/lib/types';

function safeNumber(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Object.is(value, -0) ? 0 : value;
}

function formatCurrency(value: number | null | undefined) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return '--';
  return safeValue.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatQuantity(value: number | null | undefined) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return '--';
  return safeValue.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

function formatPercent(value: number | null | undefined) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return '--';
  return `${safeValue.toFixed(2)}%`;
}

function formatCount(value: number | null | undefined, fallback: number) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return String(fallback);
  return String(Math.max(0, Math.round(safeValue)));
}

function formatTimestamp(value: string | null | undefined) {
  return formatPaperTimestamp(value);
}

function closureLabel(position: PaperPositionSummary): string {
  if (position.contract_status !== 'recorded') return 'Legacy contract unknown';
  if (position.closure_status === 'overdue_pending_quote') return 'Overdue; pending valid exit quote';
  if (position.closure_status === 'closed_late') return `Closed late by ${position.close_delay_seconds ?? '--'} seconds`;
  if (position.status === 'closed') return 'Closed';
  return 'Scheduled';
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
                <th>Actual fill</th>
                <th>Actual close</th>
                <th>Notional</th>
                <th>Gross P/L</th>
                <th>Saved exit contract</th>
                <th>Audit</th>
                <th>Actual fill / close times</th>
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
                        <div>Source scan: {position.source_run_id ?? 'unknown'}</div>
                        <div>Policy: {position.policy_id ?? 'unknown'}{position.policy_version ? ` (${position.policy_version})` : ''}</div>
                      </div>
                    </td>
                    <td>{position.side}</td>
                    <td>{formatQuantity(position.quantity)}</td>
                    <td>{formatUnitPrice(position.simulated_fill_price)}</td>
                    <td>{position.status === 'closed' ? formatUnitPrice(position.close_price) : 'pending'}</td>
                    <td>{formatCurrency(position.notional_usd)}</td>
                    <td className={pnl == null ? 'muted' : pnl >= 0 ? 'positive' : 'negative'}>
                      {pnl == null ? 'unavailable' : formatCurrency(pnl)}
                      {position.status === 'open' ? <div className="muted small">scan-mark estimate</div> : null}
                    </td>
                    <td>
                      <div>{closureLabel(position)}</div>
                      {position.contract_status === 'recorded' ? (
                        <div className="muted small">
                          Time-based · {formatHoldingDuration(position.holding_duration_seconds)} from fill
                          <div>Deadline: {formatTimestamp(position.exit_due_at)}</div>
                        </div>
                      ) : <div className="muted small">Original duration and deadline unavailable; automatic close is not scheduled.</div>}
                    </td>
                    <td>
                      {position.execution_audit_id ? `#${position.execution_audit_id}` : '--'}
                    </td>
                    <td>
                      <div className="muted small">Fill: {formatTimestamp(position.opened_at)}</div>
                      <div className="muted small">Close: {formatTimestamp(position.closed_at)}</div>
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
  defaultCollapsed = false,
}: {
  positions: PaperPositionSummary[];
  summary: PaperLedgerSummary | null;
  errorMessage?: string | null;
  latestPrices: Record<string, number>;
  highlightAuditId?: number | null;
  refreshing: boolean;
  onRefresh: () => void;
  defaultCollapsed?: boolean;
}) {
  const openPositions = positions.filter((position) => position.status === 'open');
  const closedPositions = positions.filter((position) => position.status === 'closed');
  const [expanded, setExpanded] = useState(!defaultCollapsed);
  const [reconciling, setReconciling] = useState(false);
  const [reconcileStatus, setReconcileStatus] = useState<string | null>(null);
  const supportedMarks = openPositions.map((position) => estimateUnrealizedPnl(position, latestPrices)).filter((pnl): pnl is number => pnl != null);
  const estimatedUnrealized = supportedMarks.length ? supportedMarks.reduce((sum, pnl) => sum + pnl, 0) : null;

  const runReconcile = async () => {
    setReconciling(true);
    setReconcileStatus(null);
    try {
      const report = await reconcilePaperLedger();
      setReconcileStatus(report.ok ? 'ok' : `issues: ${report.total_issues}`);
    } catch {
      setReconcileStatus('issues: 1');
    } finally {
      setReconciling(false);
    }
  };

  return (
    <section
      id="paper-ledger"
      className={`card paper-ledger-panel ${expanded ? 'is-expanded' : 'is-collapsed'}`}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ marginBottom: 8 }}>Paper Ledger</h2>
          <p className="muted" style={{ margin: 0 }}>
            Time-based paper positions and actual simulated outcomes. P/L is gross from saved
            fill and close prices; scan marks are estimates. No active stop or target orders.
          </p>
          <div className="paper-ledger-summary-row small" style={{ marginTop: 10 }}>
            <span>
              <span className="muted">Open:</span>{' '}
              {formatCount(summary?.open_positions, openPositions.length)}
            </span>
            <span>
              <span className="muted">Gross realized P/L:</span>{' '}
              {formatCurrency(summary?.total_realized_pnl ?? null)}
            </span>
            <span>
              <span className="muted">Total trades:</span>{' '}
              {formatCount(summary?.total_count, positions.length)}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'start', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setExpanded((value) => !value)}
            style={{ width: 'auto', padding: '8px 14px' }}
          >
            {expanded ? 'Collapse ledger' : 'Expand ledger'}
          </button>
          <button
            type="button"
            className="button"
            onClick={runReconcile}
            disabled={reconciling}
            style={{ width: 'auto', padding: '8px 14px' }}
          >
            {reconciling ? 'Reconciling...' : 'Reconcile now'}
          </button>
          <button
            type="button"
            className="button"
            onClick={onRefresh}
            disabled={refreshing}
            style={{ width: 'auto', padding: '8px 14px' }}
          >
            {refreshing ? 'Refreshing...' : 'Refresh ledger'}
          </button>
          {reconcileStatus ? (
            <span className="badge" aria-live="polite">
              {reconcileStatus}
            </span>
          ) : null}
        </div>
      </div>

      {errorMessage ? (
        <p className="negative small" style={{ marginTop: 12 }}>
          {errorMessage}
        </p>
      ) : null}

      {expanded ? (
        <>
      <div className="detail-panel small" style={{ marginTop: 16 }}>
        <div><span className="muted">Overdue / pending quote:</span> {summary?.overdue_positions ?? '--'}</div>
        <div><span className="muted">Closed late:</span> {summary?.late_closed_positions ?? '--'}</div>
        <div><span className="muted">Legacy contract unknown:</span> {summary?.legacy_unknown_positions ?? '--'}</div>
        <div>
          <span className="muted">Total trades:</span>{' '}
          {formatCount(summary?.total_count, positions.length)}
        </div>
        <div>
          <span className="muted">Win rate:</span> {formatPercent(summary?.win_rate_pct)}
        </div>
        <div>
          <span className="muted">Open positions:</span>{' '}
          {formatCount(summary?.open_positions, openPositions.length)}
        </div>
        <div>
          <span className="muted">Closed positions:</span>{' '}
          {formatCount(summary?.closed_positions, closedPositions.length)}
        </div>
        <div>
          <span className="muted">Total paper notional:</span>{' '}
          {formatCurrency(summary?.total_notional_usd ?? null)}
        </div>
        <div>
          <span className="muted">Gross realized P/L:</span>{' '}
          {formatCurrency(summary?.total_realized_pnl ?? null)}
        </div>
        <div>
          <span className="muted">Gross P/L:</span> {formatCurrency(summary?.gross_pnl_usd ?? null)}
        </div>
        <div>
          <span className="muted">Max drawdown:</span>{' '}
          {formatCurrency(summary?.max_drawdown_usd ?? null)}
        </div>
        <div>
          <span className="muted">Estimated gross unrealized P/L (scan marks):</span>{' '}
          {formatCurrency(estimatedUnrealized)}
          {supportedMarks.length < openPositions.length ? ` (${supportedMarks.length}/${openPositions.length} positions have marks)` : ''}
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
        </>
      ) : null}
    </section>
  );
}
