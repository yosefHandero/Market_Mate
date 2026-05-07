import { describe, expect, it } from 'vitest';
import {
  computeTradeReadiness,
  explainTradeReadiness,
  formatReadiness,
  readinessTone,
} from '@/lib/readiness';
import type { AutomationStatusResponse, DecisionRow, ScanResult } from '@/lib/types';

function baseScan(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'AAPL',
    asset_type: 'stock',
    score: 72,
    raw_score: 68,
    calibrated_confidence: 88,
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
  score_contributions: {},
  strategy_version: 'v4.0-layered',
  short_metric_summary: '--',
  last_updated: '2026-03-20T12:00:00.000Z',
  ...overrides,
});

describe('readiness helpers', () => {
  it('formats readiness as a percentage', () => {
    expect(formatReadiness(82.4)).toBe('82%');
    expect(formatReadiness(100)).toBe('100%');
  });

  it('maps tone to buckets', () => {
    expect(readinessTone(90)).toBe('high');
    expect(readinessTone(70)).toBe('high');
    expect(readinessTone(69)).toBe('watch');
    expect(readinessTone(50)).toBe('watch');
    expect(readinessTone(49)).toBe('low');
    expect(readinessTone(25)).toBe('low');
    expect(readinessTone(24)).toBe('none');
  });

  it('produces high readiness for eligible fresh provider-ok preview row', () => {
    const r = computeTradeReadiness(baseScan(), sampleDecision());
    expect(r.score).toBeGreaterThanOrEqual(80);
    expect(r.tone).toBe('high');
    expect(r.reason).toContain('Actionable');
  });

  it('falls back from calibrated confidence to score, raw score, and decision confidence', () => {
    const scoreFallback = computeTradeReadiness(
      baseScan({ calibrated_confidence: 0, score: 68 }),
      sampleDecision(),
    );
    expect(scoreFallback.baseScore).toBe(68);
    expect(scoreFallback.score).toBeGreaterThanOrEqual(60);
    expect(
      computeTradeReadiness(
        baseScan({ calibrated_confidence: 0, score: 61, raw_score: 74 }),
        sampleDecision({ confidence: 82 }),
      ).baseScore,
    ).toBe(61);
    expect(
      computeTradeReadiness(
        baseScan({ calibrated_confidence: 0, score: 0, raw_score: 74 }),
        sampleDecision({ confidence: 82 }),
      ).baseScore,
    ).toBe(74);
    expect(
      computeTradeReadiness(
        baseScan({ calibrated_confidence: 0, score: 0, raw_score: 0 }),
        sampleDecision({ confidence: 82 }),
      ).baseScore,
    ).toBe(82);
  });

  it('caps readiness for review action inside the watch range', () => {
    const r = computeTradeReadiness(
      baseScan({ recommended_action: 'review' }),
      sampleDecision({ recommended_action: 'review' }),
    );
    expect(r.score).toBeLessThanOrEqual(65);
    expect(r.score).toBeGreaterThanOrEqual(40);
    expect(r.tone).toBe('watch');
    expect(
      explainTradeReadiness(
        baseScan({ recommended_action: 'review' }),
        sampleDecision({ recommended_action: 'review' }),
      ),
    ).toContain('Watch only');
  });

  it('produces low readiness for blocked row with gate reason', () => {
    const scan = baseScan({
      recommended_action: 'blocked',
      gate_passed: false,
      gate_reason: 'Blocked by sample_size: need 20.',
      gate_checks: [
        {
          name: 'sample_size',
          passed: false,
          detail: 'stock BUY bucket has 4 1h outcomes; need 20.',
        },
      ],
    });
    const r = computeTradeReadiness(scan, sampleDecision({ recommended_action: 'blocked' }));
    expect(r.score).toBeGreaterThanOrEqual(15);
    expect(r.score).toBeLessThanOrEqual(35);
    expect(r.tone).toBe('low');
    expect(r.reason).toContain('sample size');
    expect(r.projection).toBe('blocked_until_sample_size');
  });

  it('produces low readiness for HOLD ignore row', () => {
    const scan = baseScan({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      calibrated_confidence: 90,
    });
    const r = computeTradeReadiness(
      scan,
      sampleDecision({ signal: 'HOLD', recommended_action: 'ignore' }),
    );
    expect(r.score).toBeGreaterThanOrEqual(10);
    expect(r.score).toBeLessThanOrEqual(30);
    expect(r.reason).toContain('HOLD');
  });

  it('penalizes provider degraded without automatically zeroing readiness', () => {
    const healthy = computeTradeReadiness(baseScan(), sampleDecision());
    const r = computeTradeReadiness(
      baseScan({ provider_status: 'degraded' }),
      sampleDecision({ provider_status: 'degraded' }),
    );
    expect(r.score).toBeGreaterThan(0);
    expect(r.score).toBeLessThan(healthy.score);
    expect(r.projection).toBe('decaying');
  });

  it('produces low readiness for provider critical', () => {
    const scan = baseScan({ provider_status: 'critical', recommended_action: 'preview' });
    const r = computeTradeReadiness(scan, sampleDecision());
    expect(r.score).toBeLessThan(40);
    expect(r.reason).toContain('provider');
  });

  it('penalizes stale bars', () => {
    const scan = baseScan({ bar_age_minutes: 200, recommended_action: 'preview' });
    const r = computeTradeReadiness(scan, sampleDecision());
    expect(r.score).toBeLessThanOrEqual(30);
    expect(r.reason.toLowerCase()).toMatch(/stale|bars/);
  });

  it('hard-stops provider critical when bars are stale over six hours', () => {
    const r = computeTradeReadiness(
      baseScan({ provider_status: 'critical', bar_age_minutes: 361 }),
      sampleDecision({ provider_status: 'critical', bar_age_minutes: 361 }),
    );
    expect(r.score).toBe(0);
    expect(r.hardStop).toBe(true);
  });

  it('hard-stops a missing or invalid price', () => {
    expect(computeTradeReadiness(baseScan({ price: 0 }), sampleDecision()).score).toBe(0);
    expect(computeTradeReadiness(baseScan({ price: Number.NaN }), sampleDecision()).score).toBe(0);
  });

  it('returns required factors and a projection', () => {
    const r = computeTradeReadiness(baseScan(), sampleDecision());
    expect(r.factors.map((factor) => factor.key)).toEqual([
      'signal_confidence',
      'actionability',
      'gate_status',
      'provider_health',
      'freshness',
      'risk_setup',
    ]);
    expect(r.band).toBe(r.tone);
    expect(r.reasons.length).toBeGreaterThan(0);
    expect(r.projection).toBe('stable');
  });

  it('hard-stops kill switch in reason when automation is passed', () => {
    const automation: AutomationStatusResponse = {
      enabled: false,
      phase: 'disabled',
      dry_run_only: true,
      kill_switch_enabled: true,
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
    };
    const r = computeTradeReadiness(baseScan(), sampleDecision(), { automation });
    expect(r.reason).toContain('kill switch');
    expect(r.score).toBe(0);
    expect(r.hardStop).toBe(true);
    expect(r.projection).toBe('kill_switch_or_breaker');
  });

  it('hard-stops an open breaker', () => {
    const automation: AutomationStatusResponse = {
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
        state: 'open',
        opened_at: null,
        open_until: null,
        consecutive_failures: 1,
        last_error: null,
        probe_owner: null,
        probe_expires_at: null,
      },
      recent_intents: [],
      candidates_considered: 0,
      candidates_reached_execution_call: 0,
      filter_rate_pct: null,
    };
    const r = computeTradeReadiness(baseScan(), sampleDecision(), { automation });
    expect(r.score).toBe(0);
    expect(r.reason).toContain('breaker');
  });
});
