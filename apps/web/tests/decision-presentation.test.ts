import { describe, expect, it } from 'vitest';
import {
  cardColor,
  evidenceGrade,
  formatPredictionRange,
  formatWeeklyPredictionSummary,
  resolvePricePrediction,
  riskLevel,
  topReasons,
} from '@/lib/decision-presentation';
import type { DecisionRow, ScanResult, WeeklyPatternPrediction } from '@/lib/types';

function sampleWeekly(overrides: Partial<WeeklyPatternPrediction> = {}): WeeklyPatternPrediction {
  return {
    horizon: '1w',
    horizon_label: '1 week',
    pattern_name: 'uptrend_ma_stack',
    directional_bias: 'bullish',
    range_low: 98,
    range_high: 104,
    historical_hit_rate_pct: 60,
    avg_forward_1w_return_pct: 0.5,
    sample_size: 40,
    data_quality: 'ok',
    daily_bars_stale: false,
    daily_bars_source: 'alpaca',
    forward_days: 7,
    hold_return_tolerance_pct: 1,
    evidence_basis: 'historical_only',
    real_money_trust_blocked: true,
    pattern_gate_checks: [],
    methodology: 'pattern_recognition',
    disclaimer: 'Paper-only.',
    ...overrides,
  };
}

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

function sampleDecision(overrides: Partial<DecisionRow> = {}): DecisionRow {
  return {
    symbol: 'AAPL',
    asset_type: 'stock',
    signal: 'BUY',
    confidence: 88,
    raw_score: 68,
    calibration_source: 'signal',
    confidence_label: 'moderate_evidence',
    evidence_quality: 'moderate',
    evidence_quality_score: 0.7,
    evidence_quality_reasons: ['Moderate sample'],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    provider_status: 'ok',
    gate_passed: true,
    bar_age_minutes: 5,
    signal_age_minutes: 5,
    freshness_flags: null,
    recommended_action: 'preview',
    score_contributions: { momentum: 4.2, volume: 1.1 },
    strategy_version: 'v4',
    short_metric_summary: 'BUY 1h',
    last_updated: '2026-03-20T12:00:00.000Z',
    ...overrides,
  };
}

describe('decision-presentation', () => {
  it('maps evidence quality to Strong / Mixed / Weak', () => {
    expect(evidenceGrade(sampleResult({ evidence_quality: 'high' }))).toBe('Strong');
    expect(evidenceGrade(sampleResult(), sampleDecision({ evidence_quality: 'moderate' }))).toBe(
      'Mixed',
    );
    expect(evidenceGrade(sampleResult({ evidence_quality: 'low' }))).toBe('Weak');
    expect(evidenceGrade(sampleResult({ evidence_quality: 'degraded' }))).toBe('Weak');
  });

  it('returns up to three reasons from contributions and evidence', () => {
    const reasons = topReasons(
      sampleResult({ explanation: 'Fallback explanation.' }),
      sampleDecision({
        score_contributions: { momentum: 5, volume: -2, trend: 1 },
        evidence_quality_reasons: ['Gate passed with margin'],
      }),
    );
    expect(reasons.length).toBeLessThanOrEqual(3);
    expect(reasons[0]).toMatch(/Momentum/);
  });

  it('uses buy-candidate colors (green actionable, gray blocked) without signal semantics', () => {
    expect(cardColor(false)).toBe('green');
    expect(cardColor(true)).toBe('gray');
  });

  it('derives risk level from data grade and volatility regime', () => {
    expect(riskLevel(sampleResult())).toBe('Low');
    expect(riskLevel(sampleResult({ volatility_regime: 'high', data_grade: 'degraded' }))).toBe(
      'High',
    );
  });

  it('prefers backend top reasons when present', () => {
    const reasons = topReasons(
      sampleResult(),
      sampleDecision({ top_reasons: ['Breakout structure', 'Above VWAP', 'Gate passed'] }),
    );
    expect(reasons).toEqual(['Breakout structure', 'Above VWAP', 'Gate passed']);
  });

  it('formats structural prediction range honestly', () => {
    const range = formatPredictionRange({
      range_low: 99,
      range_high: 102,
      horizon: '1h',
      horizon_label: '1 hour',
      invalidation: 'Invalidate below $99.',
      methodology: 'structural_stop_target',
      disclaimer: 'Not a guarantee.',
    });
    expect(range).toMatch(/structural stop\/target/i);
    expect(range).toMatch(/\$99\.00/);
  });

  it('surfaces the weekly trust verdict and forward range', () => {
    const summary = formatWeeklyPredictionSummary(sampleWeekly());
    expect(summary).toMatch(/Real-money trust blocked/);
    expect(summary).toMatch(/historical_only/);
    expect(summary).toMatch(/7d range/);
    expect(summary).toMatch(/data ok/);
  });

  it('marks stale daily bars distinctly and does not show fresh', () => {
    const summary = formatWeeklyPredictionSummary(
      sampleWeekly({ data_quality: 'low', daily_bars_stale: true }),
    );
    expect(summary).toMatch(/stale daily bars/);
    expect(summary).not.toMatch(/data ok/);
  });

  it('shows live-forward sufficiency only when trust is unblocked', () => {
    const summary = formatWeeklyPredictionSummary(
      sampleWeekly({ real_money_trust_blocked: false, evidence_basis: 'live_forward_proven' }),
    );
    expect(summary).toMatch(/Live-forward evidence sufficient/);
  });

  it('resolves backend price prediction from scan result', () => {
    const prediction = resolvePricePrediction(
      sampleResult({
        price_prediction: {
          range_low: 98,
          range_high: 103,
          horizon: '1h',
          horizon_label: '1 hour',
          invalidation: 'test',
          methodology: 'structural_stop_target',
          disclaimer: 'Not a guarantee.',
        },
      }),
    );
    expect(prediction?.range_high).toBe(103);
  });
});
