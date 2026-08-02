/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import ProofPage from '@/app/proof/page';

vi.mock('@/lib/api', () => ({
  getReadyz: vi.fn(async () => ({ data: { ok: true, scan_fresh: true, scheduler_enabled: false }, error: null })),
  getAutomationStatus: vi.fn(async () => ({
    data: { dry_run_only: true, kill_switch_enabled: false, breaker: { state: 'closed' } },
    error: null,
  })),
  getSystemReadiness: vi.fn(async () => ({
    data: { provider: { worst_status: 'ok', critical_count: 0 }, safety_blockers: [] },
    error: null,
  })),
  getLatestScan: vi.fn(async () => ({
    data: { market_status: 'bullish', results: [] },
    error: null,
  })),
  getPaperLedger: vi.fn(async () => ({ data: [], error: null })),
  getPaperLedgerSummary: vi.fn(async () => ({
    data: {
      open_positions: 0,
      closed_positions: 1,
      total_notional_usd: 0,
      total_realized_pnl: 5,
      total_closed_notional_usd: 100,
      long_positions: 0,
      short_positions: 0,
      last_opened_at: null,
      last_closed_at: '2026-05-18T15:00:00.000Z',
      total_count: 1,
      win_rate_pct: 100,
      gross_pnl_usd: 5,
      max_drawdown_usd: 0,
      total_unrealized_pnl: null,
    },
    error: null,
  })),
  getProofSummary: vi.fn(async () => ({
    data: {
      generated_at: '2026-05-18T15:00:00.000Z',
      ledger: {
        open_positions: 0,
        closed_positions: 1,
        total_notional_usd: 0,
        total_realized_pnl: 5,
        total_closed_notional_usd: 100,
        long_positions: 0,
        short_positions: 0,
        last_opened_at: null,
        last_closed_at: '2026-05-18T15:00:00.000Z',
        total_count: 1,
        win_rate_pct: 100,
        gross_pnl_usd: 5,
        max_drawdown_usd: 0,
        total_unrealized_pnl: 12.5,
      },
      loop_metrics: {
        recent_dry_runs: 2,
        recent_previewed: 3,
        recent_blocked: 1,
        total_audits: 6,
      },
      prediction_accuracy: {
        evaluated_count: 12,
        pending_count: 4,
        in_range_count: 7,
        in_range_rate_pct: 58.3,
        below_range_count: 3,
        above_range_count: 2,
        missed_count: 0,
        note: 'Structural range accuracy at the primary horizon. Low sample sizes are not statistically meaningful.',
      },
      confidence_performance: {
        ranking: {
          buckets: [],
          monotonic_by_group: null,
          note: 'Not enough confidence bands with resolved outcomes yet to judge ranking.',
        },
        calibration: {
          buckets: [],
          mean_abs_reliability_gap_pct: null,
          note: 'No resolved snapshots with a predicted upside probability yet.',
        },
      },
      exit_window_accuracy: {
        evaluated_count: 0,
        pending_count: 0,
        helped_count: 0,
        helped_rate_pct: null,
        by_asset_type: [],
        note: 'No prediction snapshots yet. Exit-window proof starts after BUY scans with exit targets.',
      },
      last_scan_at: '2026-05-18T15:00:00.000Z',
      scan_fresh: true,
      mark_prices_source: 'latest_scan',
      note: 'Unrealized P/L uses latest scan prices. Horizon closes use live market prices.',
    },
    error: null,
  })),
  getExecutionAudits: vi.fn(async () => ({ data: [], error: null })),
}));

vi.mock('@/components/operator-actions', () => ({
  OperatorActions: () => <div data-testid="operator-actions" />,
}));

vi.mock('@/components/proof-ledger-section', () => ({
  ProofLedgerSection: () => <div data-testid="proof-ledger" />,
}));

describe('ProofPage', () => {
  it('renders proof summary with loop metrics and unrealized P/L', async () => {
    render(await ProofPage());
    expect(screen.getByRole('heading', { name: 'Proof' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Paper loop proof' })).toBeInTheDocument();
    expect(screen.getByTestId('proof-unrealized-pnl')).toHaveTextContent('$12.50');
    expect(screen.getByTestId('prediction-in-range-rate')).toHaveTextContent('58.3%');
    expect(screen.queryByText('NaN')).not.toBeInTheDocument();
  });
});
