/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import ProofPage from '@/app/proof/page';
import { getLatestScan } from '@/lib/api';
import { getDashboardFixture } from './fixtures/dashboard-fixture';

vi.mock('@/lib/api', () => ({
  getReadyz: vi.fn(async () => ({ data: { ok: true, scan_fresh: true, scheduler_enabled: false }, error: null })),
  getAutomationStatus: vi.fn(async () => ({
    data: { dry_run_only: true, kill_switch_enabled: false, breaker: { state: 'closed' } },
    error: null,
  })),
  getSystemReadiness: vi.fn(async () => ({
    data: {
      status: 'PASS',
      reasons: ['Core safety and data checks pass'],
      provider: { worst_status: 'ok', critical_count: 0 },
      safety_blockers: [],
    },
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
      marketaux_quota: {
        configured_daily_attempt_budget: 12,
        utc_day_attempts: 4,
        operational_attempts_remaining: 8,
        block_state: 'reset_known',
        verified_reset_at: '2026-05-19T00:00:00Z',
        rate_retry_at: null,
      },
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
  it('renders safe saved provider diagnostics for HOLD rows as well as candidates', async () => {
    const scan = getDashboardFixture().latestScan;
    const row = {
      ...scan.results[0], ticker: 'CHECK', decision_signal: 'HOLD' as const,
      bar_as_of: '2026-05-18T14:58:00Z', bar_age_minutes: 2,
      price_source: 'polygon' as const, fallback_used: true,
      freshness_flags: { market_bars: 'fallback', directional_news: 'successful_empty', options_flow: 'disabled' },
      layer_details: { provider_health: {
        benchmark: {
          status: 'stale', symbols: [{
            symbol: 'SPY', provider: 'alpaca_iex', status: 'stale', as_of: '2026-05-18T13:00:00Z', age_minutes: 120,
          }],
        },
        directional_news: {
          status: 'successful_empty' as const, source: 'marketaux', providers: [
            { provider: 'finnhub', endpoint: 'https://finnhub.io/api/v1/news-sentiment?token=PRIVATE_VALUE', status: 'access_denied', http_status: 403 },
            { provider: 'marketaux', endpoint: '/v1/news/all', status: 'successful_empty' },
          ],
        },
        market_bars: {
          provider: 'polygon', endpoint: '/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from}/{to}',
          status: 'fresh', as_of: '2026-05-18T14:58:00Z', max_age_minutes: 45,
          primary_status: 'rate_limited', primary_http_status: 429, fallback_status: 'available',
        },
      } },
    };
    const skipped = {
      ...row, ticker: 'SKIP', layer_details: { provider_health: {
        directional_news: { status: 'not_requested' as const, source: 'skipped', providers: [] },
      } },
    };
    const missingSentiment = {
      ...row, ticker: 'NO-SCORE', layer_details: { provider_health: {
        directional_news: { status: 'unavailable' as const, source: '', providers: [
          { provider: 'marketaux', endpoint: '/v1/news/all', status: 'missing_sentiment', http_status: 200 },
        ] },
      } },
    };
    vi.mocked(getLatestScan).mockResolvedValueOnce({
      data: {
        ...scan, results: [row, skipped, missingSentiment],
        coverage: [{
          asset_type: 'stock', expected_symbols: ['CHECK', 'SKIP', 'NO-SCORE', 'OMITTED'],
          returned_symbols: ['CHECK', 'SKIP', 'NO-SCORE'], status: 'partial',
          missing_symbols: [{
            ticker: 'OMITTED', reason: 'analysis_skipped', required_input: 'directional_news',
            detail: 'Required directional news unavailable.', directional_news: {
              status: 'unavailable', source: 'unavailable', providers: [{
                provider: 'marketaux', endpoint: '/v1/news/all?api_token=PRIVATE_VALUE',
                status: 'invalid_publication_time', http_status: 200,
              }],
            },
          }],
        }],
      },
      error: null,
    });
    render(await ProofPage());

    const diagnostics = screen.getByLabelText('Required data diagnostics');
    expect(diagnostics).toHaveTextContent('CHECK');
    expect(diagnostics).toHaveTextContent(/Finnhub \/api\/v1\/news-sentiment.*Access denied.*HTTP 403/i);
    expect(diagnostics).toHaveTextContent(/Marketaux \/v1\/news\/all.*Successful empty/i);
    expect(diagnostics).toHaveTextContent(/Marketaux \/v1\/news\/all.*Matching articles lack usable sentiment.*HTTP 200/i);
    expect(diagnostics).toHaveTextContent(/OMITTED · Required directional news unavailable.*Marketaux.*Matching articles lack a valid publication time/i);
    expect(diagnostics).toHaveTextContent(/Relative-strength benchmark.*Stale.*SPY.*Alpaca IEX.*Age at scan 120m/i);
    expect(diagnostics).toHaveTextContent(/Polygon \/v2\/aggs\/ticker/);
    expect(diagnostics).toHaveTextContent(/Primary.*Rate limited.*HTTP 429/i);
    expect(diagnostics).toHaveTextContent(/Fallback.*Available/i);
    expect(diagnostics).toHaveTextContent('2026-05-18T14:58:00Z');
    expect(diagnostics).toHaveTextContent(/Options flow.*Intentionally disabled/i);
    expect(diagnostics).toHaveTextContent(/Directional news.*Not requested/i);
    expect(document.body).not.toHaveTextContent('PRIVATE_VALUE');
  });

  it('separates live shared quota from provider attempts recorded in a saved scan', async () => {
    render(await ProofPage());

    const diagnostics = screen.getByLabelText('Required data diagnostics');
    expect(diagnostics).toHaveTextContent('Marketaux shared quota now');
    expect(diagnostics).toHaveTextContent('4 of 12 local UTC-day attempts');
    expect(diagnostics).toHaveTextContent('8 remaining under the persisted ceiling');
    expect(diagnostics).toHaveTextContent('Verified account reset 2026-05-19T00:00:00Z');
  });

  it('explains every saved BUY evidence failure without treating detection as paper permission', async () => {
    const scan = getDashboardFixture().latestScan;
    const link = {
      ...scan.results[0], ticker: 'LINK/USD', asset_type: 'crypto' as const,
      decision_signal: 'BUY' as const, is_buy_candidate: true, is_top_pick: false,
      recommended_action: 'blocked' as const, execution_eligibility: 'blocked',
      gate_passed: false, readiness_score: 8, readiness_band: 'none' as const,
      readiness_hard_stop: false, provider_status: 'degraded',
      freshness_flags: { market_bars: 'ok', directional_news: 'missing' },
      gate_checks: [
        { name: 'sample_size', passed: false, detail: 'crypto BUY bucket has 0 1h outcomes; need 30' },
        { name: 'win_rate', passed: false, detail: 'crypto win rate 0.00% vs min 55.00%' },
        { name: 'avg_return', passed: false, detail: 'crypto avg return 0.0000% vs min 0.1500%' },
      ],
    };
    vi.mocked(getLatestScan).mockResolvedValueOnce({
      data: { ...scan, results: [link, { ...link, ticker: 'SHADOW/USD', decision_role: 'shadow' }] },
      error: null,
    });
    render(await ProofPage());
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('Detected BUY does not authorize a dry-run');
    expect(diagnostics).toHaveTextContent('LINK/USD');
    for (const check of link.gate_checks) expect(diagnostics).toHaveTextContent(check.detail);
    expect(diagnostics).toHaveTextContent('Readiness 8/100; need 70');
    expect(diagnostics).toHaveTextContent('Action blocked; need preview or dry_run');
    expect(diagnostics).toHaveTextContent('directional news: missing');
    expect(diagnostics).not.toHaveTextContent('SHADOW/USD');
  });

  it('renders proof summary with loop metrics and unrealized P/L', async () => {
    render(await ProofPage());
    expect(screen.getByRole('heading', { name: 'Proof' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Scan diagnostics' })).toBeInTheDocument();
    expect(screen.getByLabelText('Dashboard status')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Paper loop proof' })).toBeInTheDocument();
    expect(screen.getByTestId('proof-unrealized-pnl')).toHaveTextContent('$12.50');
    expect(screen.getByTestId('prediction-in-range-rate')).toHaveTextContent('58.3%');
    expect(screen.queryByText('NaN')).not.toBeInTheDocument();
  });

  it('places the paper ledger directly after the loop summary so tracking is easy to find', async () => {
    render(await ProofPage());
    const summary = screen.getByLabelText('Paper loop proof summary');
    const ledger = screen.getByTestId('proof-ledger');
    const audits = screen.getByRole('heading', { name: /recent dry-run audits/i });
    expect(summary.compareDocumentPosition(ledger) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(ledger.compareDocumentPosition(audits) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId('operator-actions').compareDocumentPosition(ledger) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });
});
