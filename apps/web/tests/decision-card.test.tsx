/**
 * @vitest-environment jsdom
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DecisionCard } from '@/components/decision-card';
import { ForecastContextPanel } from '@/components/forecast-context-panel';
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
      paper_contract: paperContract,
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
      paper_contract: paperContract,
      filled_at: '2026-04-22T18:05:00.000Z',
      exit_due_at: '2026-04-22T19:05:00.000Z',
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

const paperContract = {
  source_run_id: 'scan-1', policy_id: 'hybrid', policy_version: 'v4', decision_fingerprint: 'decision-1',
  holding_horizon: '1h', holding_duration_seconds: 3600, exit_method: 'time_based',
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('DecisionCard', () => {
  it('renders compact buy-candidate fields and keeps the rest behind details', async () => {
    const user = userEvent.setup();
    render(
      <DecisionCard
        result={sampleResult()}
        decision={sampleDecision()}
        automation={sampleAutomation()}
      />,
    );

    const card = screen.getByTestId('decision-card-AAPL');
    const summary = card.querySelector('.candidate-summary') as HTMLElement;
    expect(card).toHaveAttribute('data-color', 'green');
    expect(within(card).queryByText(/^(BUY|SELL|HOLD)$/)).not.toBeInTheDocument();
    expect(within(summary).getByTestId('current-price')).toHaveTextContent('$100.00');
    expect(within(summary).getByTestId('paper-exit-method')).toHaveTextContent('Time-based paper exit');
    expect(within(summary).getByTestId('confidence-score')).toHaveTextContent('88/100');
    expect(within(summary).queryByTestId('upside-probability')).not.toBeInTheDocument();
    expect(within(summary).queryByTestId('target-stop')).not.toBeInTheDocument();
    expect(screen.getByTestId('candidate-details')).not.toHaveAttribute('open');

    await user.click(screen.getByText('Details'));
    expect(screen.getByTestId('candidate-details')).toHaveAttribute('open');
    expect(screen.getByTestId('confidence-score')).toHaveTextContent('88');
    expect(screen.getByTestId('data-quality')).toHaveTextContent('Good');
    expect(screen.getByTestId('actionability-status')).toHaveTextContent(/paper preview eligible/i);
    expect(screen.getByTestId('evidence-provenance')).toHaveTextContent(/historical-only/i);
    expect(screen.getByTestId('exit-window-block')).toHaveTextContent('No active stop or target orders');
    expect(screen.getByTestId('forecast-proof-link')).toHaveAttribute('href', '/proof#forecast-AAPL');
    expect(card).not.toHaveTextContent('64%');
    // An eligible card states eligibility once (badge + action line); no gate echo.
    expect(screen.queryByTestId('blocked-reason')).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent(/allowed by current safety and setup gates/i);
    expect(screen.getByRole('button', { name: /preview paper trade/i })).toBeEnabled();
  });

  it('keeps unavailable weekly probability on Proof, separate from signal confidence', () => {
    render(
      <ForecastContextPanel
        results={[sampleResult({
          upside_probability_pct: null,
          weekly_prediction: undefined,
        })]}
      />,
    );

    expect(screen.getByLabelText('Signal and advisory forecast context')).toHaveTextContent(/Weekly upside probability \(advisory\): Insufficient evidence/i);
    expect(screen.getByLabelText('Signal and advisory forecast context')).toHaveTextContent('Signal confidence 88/100');
  });

  it('keeps metric labels separated from values', async () => {
    const user = userEvent.setup();
    render(
      <DecisionCard
        result={sampleResult({ price: 514.39, confidence_score: 40 })}
        decision={sampleDecision({ confidence_score: 40 })}
        automation={sampleAutomation()}
      />,
    );

    expect(screen.getByTestId('current-price')).toHaveTextContent('$514.39');
    expect(screen.getByTestId('decision-card-AAPL')).not.toHaveTextContent(/Price\$514\.39/i);
    await user.click(screen.getByText('Details'));
    const metrics = screen
      .getByTestId('decision-card-AAPL')
      .querySelector('.candidate-summary') as HTMLElement;
    expect(metrics).toHaveTextContent(/Confidence\s+40/);
    expect(metrics).not.toHaveTextContent(/Confidence40/i);
  });

  it('shows sub-cent prices and explains a missing saved price', () => {
    const { rerender } = render(<DecisionCard result={sampleResult({ price: 0.00000974 })} />);
    expect(screen.getByTestId('current-price')).toHaveTextContent('$0.00000974');
    rerender(<DecisionCard result={sampleResult({ price: 0 })} />);
    expect(screen.getByTestId('current-price')).toHaveTextContent('--');
    expect(screen.getByTestId('decision-card-AAPL')).toHaveTextContent(/saved scan price is unavailable/i);
  });

  it('renders hard-blocked stale candidates as blocked, with setup details behind Details', async () => {
    const user = userEvent.setup();
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
    expect(screen.getByTestId('actionability-status')).toHaveTextContent(/^Blocked$/);
    expect(screen.getByTestId('blocked-reason')).toHaveTextContent(/provider is critical/i);
    expect(screen.getByTestId('blocked-reason')).toHaveTextContent(/bars are stale/i);
    expect(screen.queryByRole('button', { name: /preview paper trade/i })).not.toBeInTheDocument();
    await user.click(screen.getByText('Details'));
    expect(screen.getByTestId('setup-details')).toHaveTextContent(/view setup details/i);
    expect(screen.getByTestId('setup-details')).toHaveTextContent(/provider is critical/i);
    expect(screen.queryByRole('button', { name: /preview paper trade/i })).not.toBeInTheDocument();
  });

  it('shows a live-forward-proven provenance badge when evidence is proven', async () => {
    const user = userEvent.setup();
    render(
      <DecisionCard
        result={sampleResult({ evidence_provenance: 'live_forward_proven' })}
        decision={sampleDecision({ evidence_provenance: 'live_forward_proven' })}
        automation={sampleAutomation()}
      />,
    );

    await user.click(screen.getByText('Details'));
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

    await user.click(screen.getByText('Details'));
    await user.click(screen.getByRole('button', { name: /preview paper trade/i }));
    const placeButton = await screen.findByRole('button', { name: 'Place Dry Run' });
    await user.click(placeButton);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, previewInit] = fetchMock.mock.calls[0];
    const requestedPreview = JSON.parse(String(previewInit?.body));
    expect(requestedPreview).toEqual(expect.objectContaining({ requested_notional_usd: 100 }));
    expect(requestedPreview.qty).toBeUndefined();
    expect(requestedPreview.stop_price).toBeUndefined();
    expect(requestedPreview.target_price).toBeUndefined();
    const [, placeInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String(placeInit?.body))).toEqual(
      expect.objectContaining({ dry_run: true, mode: 'dry_run', qty: 1, requested_notional_usd: null, paper_contract: paperContract }),
    );

    // After the receipt the next step is tracking, not re-placing the same setup.
    const recorded = await screen.findByRole('button', { name: 'Dry Run Recorded' });
    expect(recorded).toBeDisabled();
    expect(screen.getByTestId('receipt-ledger-link')).toHaveAttribute('href', '/proof#paper-ledger');
    expect(screen.getByTestId('paper-exit-method')).toHaveTextContent('1 hour');
    expect(screen.getByText(/Saved exit deadline:/).parentElement).not.toHaveTextContent('--');
    await user.click(recorded);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shows advisory weekly evidence on Proof without treating it as a one-hour win probability', () => {
    render(<ForecastContextPanel results={[sampleResult(), sampleResult({ ticker: 'SHADOW', decision_role: 'shadow' })]} />);
    const context = screen.getByLabelText('Signal and advisory forecast context');
    expect(context).toHaveTextContent('Weekly upside probability (advisory): 64%');
    expect(context).toHaveTextContent('historical pattern hit rate 61% (not an upside probability)');
    expect(context).toHaveTextContent('Advisory target: Estimated stop-growing point: $102.00');
    expect(context).toHaveTextContent('Advisory weekly context: Projected range: $97.00');
    expect(context).toHaveTextContent('Advisory stop: Invalidation: $99.00');
    expect(context).toHaveTextContent('That ranking is not a one-hour profit probability');
    expect(context).not.toHaveTextContent('SHADOW');
  });

  it('invalidates a preview when a new same-symbol scan replaces the candidate', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(orderPreviewResponse()));
    const result = sampleResult();
    const { rerender } = render(<DecisionCard result={result} decision={sampleDecision()} automation={sampleAutomation()} />);
    await user.click(screen.getByText('Details'));
    await user.click(screen.getByRole('button', { name: /preview paper trade/i }));
    expect(await screen.findByRole('button', { name: 'Place Dry Run' })).toBeEnabled();
    rerender(<DecisionCard result={{ ...result, created_at: '2026-04-22T18:10:00.000Z', price: 101 }} decision={sampleDecision()} automation={sampleAutomation()} />);
    expect(screen.queryByRole('button', { name: 'Place Dry Run' })).not.toBeInTheDocument();
  });
});
