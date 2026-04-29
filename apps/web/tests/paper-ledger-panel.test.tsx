/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { PaperLedgerPanel } from '@/components/paper-ledger-panel';
import type { PaperLedgerSummary, PaperPositionSummary } from '@/lib/types';

const positions: PaperPositionSummary[] = [
  {
    id: 1,
    intent_key: 'intent-open',
    execution_audit_id: 44,
    ticker: 'AAPL',
    asset_type: 'stock',
    side: 'buy',
    quantity: 2,
    simulated_fill_price: 100,
    notional_usd: 200,
    cost_basis_usd: 200,
    close_price: null,
    realized_pnl: null,
    status: 'open',
    opened_at: '2026-04-22T16:00:00.000Z',
    closed_at: null,
    strategy_version: 'v3',
    confidence: 72,
  },
  {
    id: 2,
    intent_key: 'intent-closed',
    execution_audit_id: 45,
    ticker: 'MSFT',
    asset_type: 'stock',
    side: 'sell',
    quantity: 1,
    simulated_fill_price: 410,
    notional_usd: 410,
    cost_basis_usd: 410,
    close_price: 400,
    realized_pnl: 10,
    status: 'closed',
    opened_at: '2026-04-22T15:00:00.000Z',
    closed_at: '2026-04-22T17:00:00.000Z',
    strategy_version: 'v3',
    confidence: 68,
  },
];

const summary: PaperLedgerSummary = {
  open_positions: 1,
  closed_positions: 1,
  total_notional_usd: 610,
  total_realized_pnl: 10,
  total_closed_notional_usd: 410,
  long_positions: 1,
  short_positions: 1,
  last_opened_at: '2026-04-22T16:00:00.000Z',
  last_closed_at: '2026-04-22T17:00:00.000Z',
  total_count: 2,
  win_rate_pct: 100,
  gross_pnl_usd: 10,
  max_drawdown_usd: 0,
};

describe('PaperLedgerPanel', () => {
  it('shows open and closed paper positions with ledger performance', () => {
    render(
      React.createElement(PaperLedgerPanel, {
        positions,
        summary,
        errorMessage: null,
        latestPrices: { 'STOCK:AAPL': 103 },
        refreshing: false,
        onRefresh: vi.fn(),
      }),
    );

    expect(screen.getByText('Open Paper Positions')).toBeInTheDocument();
    expect(screen.getByText('Closed Paper Positions')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText('#44')).toBeInTheDocument();
    expect(screen.getByText('#45')).toBeInTheDocument();
    expect(screen.getByText('100.00%')).toBeInTheDocument();
    expect(screen.getAllByText('$6.00').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$10.00').length).toBeGreaterThan(0);
  });

  it('calls onRefresh from the refresh button', async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      React.createElement(PaperLedgerPanel, {
        positions,
        summary,
        errorMessage: null,
        latestPrices: { 'STOCK:AAPL': 103 },
        refreshing: false,
        onRefresh,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Refresh ledger' }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('marks the row matching the highlighted audit id', () => {
    render(
      React.createElement(PaperLedgerPanel, {
        positions,
        summary,
        errorMessage: null,
        latestPrices: { 'STOCK:AAPL': 103 },
        highlightAuditId: 44,
        refreshing: false,
        onRefresh: vi.fn(),
      }),
    );

    expect(screen.getByText('AAPL').closest('tr')).toHaveAttribute('data-highlight', 'true');
    expect(screen.getByText('MSFT').closest('tr')).not.toHaveAttribute('data-highlight');
  });
});
