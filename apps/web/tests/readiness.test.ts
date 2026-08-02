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
    readiness_score: 88,
    readiness_band: 'high',
    readiness_hard_stop: false,
    readiness_reason: 'Actionable: gates passed and data is fresh.',
    selection_rank: 1,
    is_top_pick: true,
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
  readiness_score: 88,
  readiness_band: 'high',
  readiness_hard_stop: false,
  readiness_reason: 'Actionable: gates passed and data is fresh.',
  selection_rank: 1,
  is_top_pick: true,
  score_contributions: {},
  strategy_version: 'v4.0-layered',
  short_metric_summary: '--',
  last_updated: '2026-03-20T12:00:00.000Z',
  ...overrides,
});

describe('readiness presenter', () => {
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

  it('renders backend readiness for an actionable row', () => {
    const readiness = computeTradeReadiness(baseScan(), sampleDecision());
    expect(readiness.score).toBe(88);
    expect(readiness.tone).toBe('high');
    expect(readiness.reason).toContain('Actionable');
  });

  it('uses backend review reason and band', () => {
    const readiness = computeTradeReadiness(
      baseScan({
        readiness_score: 55,
        readiness_band: 'watch',
        readiness_reason: 'Watch only: review pending.',
        recommended_action: 'review',
      }),
      sampleDecision({ recommended_action: 'review' }),
    );
    expect(readiness.score).toBe(55);
    expect(readiness.tone).toBe('watch');
    expect(
      explainTradeReadiness(
        baseScan({
          recommended_action: 'review',
          readiness_score: 55,
          readiness_band: 'watch',
          readiness_reason: 'Watch only: review pending.',
        }),
        sampleDecision({ recommended_action: 'review' }),
      ),
    ).toContain('Watch only');
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
    const readiness = computeTradeReadiness(baseScan(), sampleDecision(), { automation });
    expect(readiness.reason).toContain('kill switch');
    expect(readiness.score).toBe(0);
    expect(readiness.hardStop).toBe(true);
    expect(readiness.projection).toBe('kill_switch_or_breaker');
  });

  it('hard-stops an open breaker even when backend score is high', () => {
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
    const readiness = computeTradeReadiness(baseScan(), sampleDecision(), { automation });
    expect(readiness.score).toBe(0);
    expect(readiness.reason).toContain('breaker');
  });
});
