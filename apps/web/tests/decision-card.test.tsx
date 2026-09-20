/**
 * @vitest-environment jsdom
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DecisionCard } from '@/components/decision-card';
import type { AutomationStatusResponse, DecisionRow, ScanResult } from '@/lib/types';

function sampleResult(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'AAPL',
    asset_type: 'stock',
    score: 72,
    raw_score: 68,
    calibrated_confidence: 88,
    calibration_source: 'signal',
    confidence_label: 'moderate_evidence',
    strategy_id: 'scanner-directional',
    strategy_version: 'v4',
    strategy_primary_horizon: '1h',
    strategy_entry_assumption: 'entry',
    strategy_exit_assumption: 'exit',
    evidence_quality: 'high',
    evidence_quality_score: 0.82,
    evidence_quality_reasons: ['Strong alignment'],
    evidence_grade: 'Strong',
    top_reasons: ['Breakout structure', 'Above VWAP', 'Momentum (+5.0)'],
    price_prediction: {
      range_low: 99,
      range_high: 102,
      horizon: '1h',
      horizon_label: '1 hour',
      invalidation: 'Invalidate if price closes below $99.00 (structural stop).',
      methodology: 'structural_stop_target',
      disclaimer: 'Structural stock range from stop/target levels aligned with paper sizing. Not a guarantee or price target.',
    },
    weekly_prediction: {
      horizon: '1w',
      horizon_label: '1 week',
      pattern_name: 'breakout_20d_high',
      directional_bias: 'bullish',
      range_low: 97,
      range_high: 110,
      upside_probability_pct: 64,
      historical_hit_rate_pct: 61,
      avg_forward_1w_return_pct: 1.2,
      sample_size: 40,
      data_quality: 'ok',
      evidence_basis: 'historical_only',
      real_money_trust_blocked: true,
      pattern_gate_checks: [],
      methodology: 'pattern_recognition',
      disclaimer: 'Weekly pattern prediction.',
    },
    exit_window: {
      expected_growth_window_label: '~1 week (7 trading-day horizon)',
      expected_growth_days: 7,
      estimated_exit_price: 102,
      projected_range_low: 97,
      projected_range_high: 110,
      invalidation_level: 99,
      invalidation_note: 'Invalidate if price closes below $99.00 (structural stop).',
      stop_growing_signal: 'Growth likely to slow near $102.00 (about +2.0%).',
      stop_growing_conditions: ['Price closes back below the prior 20-day breakout high.'],
      risk_warning: 'Standard market risk applies; upside is not guaranteed.',
      confidence_change_note: 'Historical evidence only; not yet live-proven.',
      methodology: 'weekly_pattern_exit_window',
      disclaimer: 'Exit window is a forecast, not a sell order.',
    },
    upside_probability_pct: 64,
    confidence_score: 88,
    evidence_provenance: 'historical_only',
    is_buy_candidate: true,
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Momentum expanding.',
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
    signal_label: 'strong',
    data_quality: 'ok',
    volatility_regime: 'normal',
    benchmark_ticker: 'SPY',
    benchmark_change_pct: 0.8,
    recommended_action: 'preview',
    readiness_score: 85,
    readiness_band: 'high',
    readiness_reason: 'Actionable: gates passed and data is fresh.',
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
  confidence: 88,
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
  readiness_score: 85,
  readiness_band: 'high',
  score_contributions: {},
  strategy_version: 'v4',
  short_metric_summary: '--',
  last_updated: '2026-03-20T12:00:00.000Z',
  ...overrides,
});

const sampleAutomation = (): AutomationStatusResponse => ({
  enabled: false,
  phase: 'disabled',
  dry_run_only: true,
  kill_switch_enabled: false,
  scheduler_triggered: false,
  last_processed_run_id: null,
  last_processed_run_at: null,
  last_recovery_at: null,
  requests_made: 0,
  requests_avoided: 0,
  dedupe_hits: 0,
  retries: 0,
  blocked_by_budget: 0,
  blocked_by_gate: 0,
  blocked_by_cooldown: 0,
  blocked_by_circuit: 0,
  recent_status_counts: {},
  budget: {
    hourly_limit: 0,
    hourly_used: 0,
    daily_limit: 0,
    daily_used: 0,
    per_symbol_window_limit: 0,
    per_symbol_window_seconds: 0,
    per_cycle_limit: 0,
  },
  breaker: {
    state: 'closed',
    opened_at: null,
    open_until: null,
    consecutive_failures: 0,
    last_error: null,
    probe_owner: null,
    probe_expires_at: null,
  },
  recent_intents: [],
  candidates_considered: 0,
  candidates_reached_execution_call: 0,
  filter_rate_pct: null,
});

function orderPreviewResponse() {
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
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

function orderPlaceResponse() {
  return new Response(
    JSON.stringify({
      ok: true,
      broker: 'alpaca',
      submitted: false,
      dry_run: true,
      message: 'Dry run only.',
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
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('DecisionCard', () => {
  it('renders buy-candidate fields and exit window without any BUY/SELL/HOLD label', () => {
    render(
      <DecisionCard
        result={sampleResult()}
        decision={sampleDecision()}
        automation={sampleAutomation()}
      />,
    );

    const card = screen.getByTestId('decision-card-AAPL');
    expect(card).toHaveAttribute('data-color', 'green');
    // No BUY/SELL/HOLD signal label anywhere on the card.
    expect(within(card).queryByText(/^(BUY|SELL|HOLD)$/)).not.toBeInTheDocument();
    // Required buy-candidate fields.
    expect(screen.getByTestId('upside-probability')).toHaveTextContent('64%');
    expect(screen.getByTestId('confidence-score')).toHaveTextContent('88');
    expect(screen.getByTestId('data-quality')).toHaveTextContent('Good');
    expect(screen.getByTestId('current-price')).toHaveTextContent('$100.00');
    expect(screen.getByTestId('actionability-status')).toHaveTextContent(/paper preview eligible/i);
    expect(screen.getByTestId('pattern-name')).toHaveTextContent(/breakout_20d_high/i);
    expect(screen.getByTestId('evidence-provenance')).toHaveTextContent(/historical-only/i);
    // Exit window / stop-growing instead of a SELL label.
    expect(screen.getByTestId('expected-growth-window')).toHaveTextContent(/week/i);
    expect(screen.getByTestId('estimated-exit')).toHaveTextContent(/\$102\.00/);
    expect(screen.getByTestId('projected-range')).toHaveTextContent(/\$97\.00/);
    expect(screen.getByTestId('invalidation-level')).toHaveTextContent(/\$99\.00/);
    expect(screen.getByTestId('risk-warning')).toBeInTheDocument();
    expect(screen.getByTestId('blocked-reason')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /preview paper trade/i })).toBeEnabled();
  });

  it('shows insufficient evidence when no upside probability is available', () => {
    render(
      <DecisionCard
        result={sampleResult({
          upside_probability_pct: null,
          weekly_prediction: undefined,
        })}
        decision={sampleDecision({ upside_probability_pct: null })}
        automation={sampleAutomation()}
      />,
    );

    expect(screen.getByTestId('upside-probability')).toHaveTextContent(/insufficient evidence/i);
    expect(screen.getByTestId('upside-probability').closest('.decision-card-metric')).toHaveTextContent(
      /Upside probability\s+Insufficient evidence/i,
    );
  });

  it('keeps metric labels separated from values', () => {
    render(
      <DecisionCard
        result={sampleResult({ price: 514.39, confidence_score: 40 })}
        decision={sampleDecision({ confidence_score: 40 })}
        automation={sampleAutomation()}
      />,
    );

    const metrics = screen
      .getByTestId('decision-card-AAPL')
      .querySelector('.decision-card-metrics') as HTMLElement;
    expect(metrics).toHaveTextContent(/Confidence\s+40/);
    expect(metrics).toHaveTextContent(/Price\s+\$514\.39/);
    expect(metrics).not.toHaveTextContent(/Confidence40/i);
    expect(metrics).not.toHaveTextContent(/Price\$514\.39/i);
  });

  it('renders hard-blocked stale candidates as read-only setup details without preview action', () => {
    render(
      <DecisionCard
        result={sampleResult({
          recommended_action: 'blocked',
          gate_passed: false,
          gate_reason: 'Blocked by freshness.',
          execution_eligibility: 'blocked',
          provider_status: 'critical',
          bar_age_minutes: 420,
          freshness_flags: { bars: 'stale' },
          readiness_hard_stop: true,
          readiness_reason: 'Hard stop: provider is critical and bars are stale over 6 hours.',
        })}
        decision={sampleDecision({
          recommended_action: 'blocked',
          execution_eligibility: 'blocked',
          gate_passed: false,
          provider_status: 'critical',
          bar_age_minutes: 420,
          freshness_flags: { bars: 'stale' },
          readiness_hard_stop: true,
          readiness_reason: 'Hard stop: provider is critical and bars are stale over 6 hours.',
        })}
        automation={sampleAutomation()}
      />,
    );

    const card = screen.getByTestId('decision-card-AAPL');
    expect(card).toHaveAttribute('data-color', 'gray');
    expect(screen.getByTestId('actionability-status')).toHaveTextContent(/read-only setup/i);
    expect(screen.queryByRole('button', { name: /preview paper trade/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('setup-details')).toHaveTextContent(/view setup details/i);
    expect(screen.getByTestId('setup-details')).toHaveTextContent(/provider is critical/i);
    expect(screen.getByTestId('setup-details')).toHaveTextContent(/bars are stale/i);
  });

  it('shows a live-forward-proven provenance badge when evidence is proven', () => {
    render(
      <DecisionCard
        result={sampleResult({ evidence_provenance: 'live_forward_proven' })}
        decision={sampleDecision({ evidence_provenance: 'live_forward_proven' })}
        automation={sampleAutomation()}
      />,
    );

    expect(screen.getByTestId('evidence-provenance')).toHaveTextContent(/live-forward evidence/i);
  });

  it('places a dry-run after preview with forced dry_run body', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(orderPreviewResponse())
      .mockResolvedValueOnce(orderPlaceResponse());
    vi.stubGlobal('fetch', fetchMock);

    render(
      <DecisionCard
        result={sampleResult()}
        decision={sampleDecision()}
        automation={sampleAutomation()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /preview paper trade/i }));
    const placeButton = await screen.findByRole('button', { name: 'Place Dry Run' });
    await user.click(placeButton);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, placeInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String(placeInit?.body))).toEqual(
      expect.objectContaining({ dry_run: true, mode: 'dry_run' }),
    );
  });
});
