/**
 * @vitest-environment jsdom
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PaperTradingLoop } from '@/components/paper-trading-loop';
import type { DecisionRow, ScanResult } from '@/lib/types';

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

const sampleDecision = (overrides: Partial<DecisionRow> = {}): DecisionRow => ({
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
  ...overrides,
});

function orderPreviewResponse(overrides: Record<string, unknown> = {}) {
  return new Response(
    JSON.stringify({
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
      ...overrides,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

function orderPlaceResponse(overrides: Record<string, unknown> = {}) {
  return new Response(
    JSON.stringify({
      ok: true,
      broker: 'alpaca',
      submitted: false,
      dry_run: true,
      message: 'Dry run only. Order was not sent to Alpaca.',
      idempotency_key: 'server-key',
      order_id: null,
      status: 'dry_run',
      raw: {},
      trade_gate: null,
      execution_audit_id: 44,
      ledger_id: 7,
      fill_price: 100,
      filled_qty: 1,
      slippage_assumption_bps: 0,
      recommended_action_snapshot: 'preview',
      ...overrides,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('PaperTradingLoop', () => {
  it('keeps preview disabled until the selected action is previewable', () => {
    render(
      React.createElement(PaperTradingLoop, {
        selectedResult: sampleResult({ recommended_action: 'review' }),
        selectedDecision: sampleDecision({ recommended_action: 'review' }),
        onPaperOrderPlaced: vi.fn(),
      }),
    );

    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
    expect(screen.getByText(/Preview is disabled/)).toBeInTheDocument();
  });

  it('places a dry-run after preview succeeds and renders an audit receipt', async () => {
    const user = userEvent.setup();
    const onPaperOrderPlaced = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(orderPreviewResponse())
      .mockResolvedValueOnce(orderPlaceResponse());
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(PaperTradingLoop, {
        selectedResult: sampleResult(),
        selectedDecision: sampleDecision(),
        onPaperOrderPlaced,
      }),
    );

    const placeButton = screen.getByRole('button', { name: 'Place dry run' });
    expect(placeButton).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText(/Est. P\/L:/)).toBeInTheDocument();
    expect(placeButton).toBeEnabled();

    await user.click(placeButton);

    await waitFor(() => expect(onPaperOrderPlaced).toHaveBeenCalledWith(44));
    expect(screen.getByText(/Audit receipt:/)).toBeInTheDocument();
    expect(screen.getByText('Ledger id:')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();

    const [, previewInit] = fetchMock.mock.calls[0];
    const [, placeInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String(previewInit?.body))).toEqual(
      expect.objectContaining({ recommended_action_snapshot: 'preview' }),
    );
    expect(JSON.parse(String(placeInit?.body))).toEqual(
      expect.objectContaining({ recommended_action_snapshot: 'preview' }),
    );
  });

  it('reuses one idempotency key across place retries in the same preview cycle', async () => {
    const user = userEvent.setup();
    const onPaperOrderPlaced = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(orderPreviewResponse())
      .mockResolvedValueOnce(orderPlaceResponse())
      .mockResolvedValueOnce(orderPlaceResponse());
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(PaperTradingLoop, {
        selectedResult: sampleResult(),
        selectedDecision: sampleDecision(),
        onPaperOrderPlaced,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Preview' }));
    const placeButton = screen.getByRole('button', { name: 'Place dry run' });
    await waitFor(() => expect(placeButton).toBeEnabled());

    await user.click(placeButton);
    await waitFor(() => expect(onPaperOrderPlaced).toHaveBeenCalledTimes(1));

    await user.click(placeButton);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    const firstPlaceHeaders = new Headers(fetchMock.mock.calls[1][1]?.headers);
    const secondPlaceHeaders = new Headers(fetchMock.mock.calls[2][1]?.headers);
    expect(firstPlaceHeaders.get('X-Idempotency-Key')).toBeTruthy();
    expect(firstPlaceHeaders.get('X-Idempotency-Key')).toBe(
      secondPlaceHeaders.get('X-Idempotency-Key'),
    );
    expect(onPaperOrderPlaced).toHaveBeenCalledTimes(1);
  });

  it('creates a new idempotency key after the selected ticker changes and preview reruns', async () => {
    const user = userEvent.setup();
    let currentNow = 1000;
    vi.spyOn(Date, 'now').mockImplementation(() => currentNow);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(orderPreviewResponse())
      .mockResolvedValueOnce(orderPlaceResponse())
      .mockResolvedValueOnce(orderPreviewResponse({ ticker: 'TSLA', execution_audit_id: 55 }))
      .mockResolvedValueOnce(
        orderPlaceResponse({ ticker: 'TSLA', execution_audit_id: 55, ledger_id: 8 }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { rerender } = render(
      React.createElement(PaperTradingLoop, {
        selectedResult: sampleResult(),
        selectedDecision: sampleDecision(),
        onPaperOrderPlaced: vi.fn(),
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Place dry run' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Place dry run' }));

    rerender(
      React.createElement(PaperTradingLoop, {
        selectedResult: sampleResult({ ticker: 'TSLA' }),
        selectedDecision: sampleDecision({ symbol: 'TSLA' }),
        onPaperOrderPlaced: vi.fn(),
      }),
    );

    currentNow = 2000;
    await waitFor(() => expect(screen.getByText('TSLA')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Place dry run' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Place dry run' }));

    const firstPlaceHeaders = new Headers(fetchMock.mock.calls[1][1]?.headers);
    const secondPlaceHeaders = new Headers(fetchMock.mock.calls[3][1]?.headers);
    expect(firstPlaceHeaders.get('X-Idempotency-Key')).toBeTruthy();
    expect(secondPlaceHeaders.get('X-Idempotency-Key')).toBeTruthy();
    expect(firstPlaceHeaders.get('X-Idempotency-Key')).not.toBe(
      secondPlaceHeaders.get('X-Idempotency-Key'),
    );
  });
});
