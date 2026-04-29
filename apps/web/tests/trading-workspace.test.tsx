/**
 * @vitest-environment jsdom
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TradingWorkspace } from '@/components/trading-workspace';
import type { DecisionRow, PaperLedgerSummary, PaperPositionSummary, ScanResult, ScanRun } from '@/lib/types';

function sampleResult(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'AAPL',
    asset_type: 'stock',
    score: 72,
    raw_score: 68,
    calibrated_confidence: 72,
    calibration_source: 'signal',
    confidence_label: 'moderate_evidence',
    strategy_id: 'scanner-directional',
    strategy_version: 'v4.0-layered',
    strategy_primary_horizon: '1h',
    strategy_entry_assumption: 'Break above session high',
    strategy_exit_assumption: 'Trail into close',
    evidence_quality: 'high',
    evidence_quality_score: 0.82,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Momentum is expanding.',
    price: 100,
    price_change_pct: 2,
    relative_volume: 1.4,
    relative_strength_pct: 0.6,
    sentiment_score: 0.2,
    filing_flag: false,
    breakout_flag: true,
    market_status: 'bullish',
    sector_strength_score: 0.5,
    options_flow_score: 0.4,
    options_flow_summary: 'Calls leading.',
    options_flow_bullish: true,
    options_call_put_ratio: 1.3,
    alert_sent: false,
    news_checked: true,
    news_source: 'marketaux',
    news_cache_label: null,
    signal_label: 'aggressive',
    data_quality: 'ok',
    volatility_regime: 'normal',
    benchmark_ticker: 'SPY',
    benchmark_change_pct: 0.8,
    recommended_action: 'preview',
    gate_passed: true,
    gate_reason: 'Passed',
    gate_checks: [],
    coingecko_price_change_pct_24h: null,
    coingecko_market_cap_rank: null,
    fear_greed_value: null,
    fear_greed_label: null,
    provider_status: 'ok',
    provider_warnings: [],
    bar_age_minutes: 5,
    freshness_flags: {},
    created_at: '2026-04-22T18:00:00.000Z',
    ...overrides,
  };
}

function sampleRun(results: ScanResult[]): ScanRun {
  return {
    run_id: 'run-1',
    created_at: '2026-04-22T18:00:00.000Z',
    market_status: 'bullish',
    scan_count: results.length,
    watchlist_size: results.length,
    alerts_sent: 0,
    fear_greed_value: null,
    fear_greed_label: null,
    results,
  };
}

const decisions: DecisionRow[] = [
  {
    symbol: 'AAPL',
    asset_type: 'stock',
    signal: 'BUY',
    confidence: 72,
    raw_score: 68,
    calibration_source: 'signal',
    confidence_label: 'moderate_evidence',
    evidence_quality: 'high',
    evidence_quality_score: 0.85,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    provider_status: 'ok',
    gate_passed: true,
    bar_age_minutes: 5,
    signal_age_minutes: 5,
    freshness_flags: null,
    recommended_action: 'preview',
    score_contributions: {},
    strategy_version: 'v4.0-layered',
    short_metric_summary: '--',
    last_updated: '2026-03-20T12:00:00.000Z',
  },
  {
    symbol: 'TSLA',
    asset_type: 'stock',
    signal: 'SELL',
    confidence: 68,
    raw_score: 64,
    calibration_source: 'signal',
    confidence_label: 'moderate_evidence',
    evidence_quality: 'high',
    evidence_quality_score: 0.8,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    provider_status: 'ok',
    gate_passed: true,
    bar_age_minutes: 5,
    signal_age_minutes: 5,
    freshness_flags: null,
    recommended_action: 'dry_run',
    score_contributions: {},
    strategy_version: 'v4.0-layered',
    short_metric_summary: '--',
    last_updated: '2026-03-20T12:00:00.000Z',
  },
];

const summary: PaperLedgerSummary = {
  open_positions: 0,
  closed_positions: 0,
  total_notional_usd: 0,
  total_realized_pnl: 0,
  total_closed_notional_usd: 0,
  long_positions: 0,
  short_positions: 0,
  last_opened_at: null,
  last_closed_at: null,
  total_count: 0,
  win_rate_pct: null,
  gross_pnl_usd: 0,
  max_drawdown_usd: 0,
};

const placedPosition: PaperPositionSummary = {
  id: 1,
  intent_key: 'dashboard-paper-stock-AAPL-buy',
  execution_audit_id: 44,
  ticker: 'AAPL',
  asset_type: 'stock',
  side: 'buy',
  quantity: 1,
  simulated_fill_price: 100,
  notional_usd: 100,
  cost_basis_usd: 100,
  close_price: null,
  realized_pnl: null,
  status: 'open',
  opened_at: '2026-04-22T18:00:00.000Z',
  closed_at: null,
  strategy_version: 'v4.0-layered',
  confidence: 72,
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function flushAsyncUpdates() {
  await act(async () => {
    for (let index = 0; index < 10; index += 1) {
      await Promise.resolve();
    }
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('TradingWorkspace', () => {
  it('updates the paper loop when a RankTable ticker is selected', async () => {
    const user = userEvent.setup();
    const positions: PaperPositionSummary[] = [];

    render(
      React.createElement(TradingWorkspace, {
        decisions,
        decisionsError: null,
        latestScan: sampleRun([
          sampleResult(),
          sampleResult({ ticker: 'TSLA', decision_signal: 'SELL', price: 200 }),
        ]),
        initialPaperPositions: positions,
        initialPaperSummary: summary,
        paperLedgerError: null,
      }),
    );

    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0);
    expect(screen.getByText('BUY | preview')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /TSLA/i }));

    expect(screen.getByText('SELL | dry_run')).toBeInTheDocument();
  });

  it('highlights the placed ledger row and clears the highlight after the timeout', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          broker: 'alpaca',
          ticker: 'AAPL',
          side: 'buy',
          qty: 1,
          order_type: 'market',
          notional_estimate: 100,
          latest_price: 100,
          time_in_force: 'day',
          warnings: [],
          trade_gate: { allowed: true, reason: 'Eligible.', gate_checks: [] },
          execution_audit_id: 44,
          entry_price: 100,
          stop_price: 99,
          target_price: 102,
          position_size: 1,
          estimated_pnl_usd: 2,
          gate_result: 'allowed',
          freshness: 'fresh',
          reject_reasons: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
          broker: 'alpaca',
          submitted: false,
          dry_run: true,
          message: 'Dry run only. Order was not sent to Alpaca.',
          idempotency_key: 'paper-key',
          order_id: null,
          status: 'dry_run',
          raw: {},
          trade_gate: null,
          execution_audit_id: 44,
          ledger_id: 1,
          fill_price: 100,
          filled_qty: 1,
          slippage_assumption_bps: 0,
          recommended_action_snapshot: 'preview',
        }),
      )
      .mockResolvedValueOnce(jsonResponse([placedPosition]))
      .mockResolvedValueOnce(jsonResponse({ ...summary, open_positions: 1, total_count: 1 }));
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(TradingWorkspace, {
        decisions,
        decisionsError: null,
        latestScan: sampleRun([sampleResult()]),
        initialPaperPositions: [],
        initialPaperSummary: summary,
        paperLedgerError: null,
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await flushAsyncUpdates();
    expect(screen.getByRole('button', { name: 'Place dry run' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Place dry run' }));
    await flushAsyncUpdates();

    expect(screen.getByText('#44').closest('tr')).toHaveAttribute('data-highlight', 'true');

    await act(async () => {
      vi.advanceTimersByTime(6000);
    });

    expect(screen.getByText('#44').closest('tr')).not.toHaveAttribute('data-highlight');
  });
});
