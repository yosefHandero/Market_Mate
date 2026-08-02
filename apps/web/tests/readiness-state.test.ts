import { describe, expect, it } from 'vitest';
import {
  classifyReadinessState,
  computeTradeReadiness,
  readinessReasonChips,
  readinessStateLabel,
} from '@/lib/readiness';
import type { AutomationStatusResponse, ScanResult } from '@/lib/types';

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
    strategy_version: 'v4.0-layered',
    strategy_primary_horizon: '1h',
    strategy_entry_assumption: 'Break',
    strategy_exit_assumption: 'Trail',
    evidence_quality: 'high',
    evidence_quality_score: 0.82,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Momentum.',
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
    created_at: '2026-04-22T18:00:00.000Z',
    ...overrides,
  };
}

const automationKill: AutomationStatusResponse = {
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

describe('readiness state classifier', () => {
  it('classifies kill switch as system issue', () => {
    const result = sampleResult();
    const readiness = computeTradeReadiness(result, null, { automation: automationKill });
    expect(classifyReadinessState(result, readiness, null, { automation: automationKill })).toBe(
      'system_issue',
    );
    expect(readinessStateLabel('system_issue')).toBe('SYSTEM ISSUE');
  });

  it('classifies HOLD as no setup', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      readiness_score: 12,
      readiness_band: 'low',
      readiness_reason: 'Low actionability: HOLD signal with usable data.',
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('no_setup');
  });

  it('classifies HOLD with gate_passed=false and HOLD gate_reason as no setup', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
      readiness_score: 12,
      readiness_band: 'low',
      readiness_reason: 'Low actionability: HOLD signal with usable data.',
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('no_setup');
    expect(readinessStateLabel('no_setup')).toBe('NO SETUP');
    expect(readiness.reason).toContain('HOLD');
    expect(readiness.reason).not.toMatch(/^Blocked:/);
  });

  it('classifies real BUY gate failure as blocked', () => {
    const result = sampleResult({
      decision_signal: 'BUY',
      recommended_action: 'blocked',
      gate_passed: false,
      gate_reason: 'risk/reward below threshold',
      gate_checks: [
        { name: 'risk_reward', passed: false, detail: 'risk/reward below threshold' },
      ],
      readiness_score: 21,
      readiness_band: 'low',
      readiness_reason: 'Blocked: risk/reward below threshold',
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('blocked');
    expect(readinessStateLabel('blocked')).toBe('SETUP BLOCKED');
    expect(readiness.reason).toMatch(/^Blocked:/);
  });

  it('classifies sample-size-only gate failure as sample_size', () => {
    const result = sampleResult({
      gate_passed: false,
      gate_reason: 'Blocked by sample_size: need 20.',
      gate_checks: [
        {
          name: 'sample_size',
          passed: false,
          detail: 'stock BUY bucket has 4 1h outcomes; need 20.',
        },
      ],
      readiness_score: 18,
      readiness_band: 'low',
      readiness_reason: 'Low trust: blocked only by sample size, not by a hard safety stop.',
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('sample_size');
    expect(readinessStateLabel('sample_size')).toBe('SAMPLE SIZE');
  });

  it('system issue wins over HOLD no_setup for kill switch', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
    });
    const readiness = computeTradeReadiness(result, null, { automation: automationKill });
    expect(classifyReadinessState(result, readiness, null, { automation: automationKill })).toBe(
      'system_issue',
    );
  });

  it('system issue wins over HOLD no_setup for open breaker', () => {
    const automation: AutomationStatusResponse = {
      ...automationKill,
      kill_switch_enabled: false,
      breaker: { ...automationKill.breaker, state: 'open' },
    };
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
    });
    const readiness = computeTradeReadiness(result, null, { automation });
    expect(classifyReadinessState(result, readiness, null, { automation })).toBe('system_issue');
  });

  it('system issue wins over HOLD no_setup for critical provider', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      provider_status: 'critical',
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('system_issue');
  });

  it('system issue wins over HOLD no_setup for missing price hard stop', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      price: 0,
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
      readiness_score: 0,
      readiness_band: 'none',
      readiness_hard_stop: true,
      readiness_reason: 'Hard stop: missing or invalid trigger price.',
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('system_issue');
  });

  it('system issue wins over HOLD no_setup for severe stale bars', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      bar_age_minutes: 400,
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
    });
    const readiness = computeTradeReadiness(result);
    expect(classifyReadinessState(result, readiness)).toBe('system_issue');
  });

  it('omits misleading gate chip for HOLD gate-not-applicable', () => {
    const result = sampleResult({
      decision_signal: 'HOLD',
      recommended_action: 'ignore',
      gate_passed: false,
      gate_reason: 'Signal is HOLD, so trade gate is not applicable.',
      gate_checks: [],
    });
    const readiness = computeTradeReadiness(result);
    const chips = readinessReasonChips(result, readiness);
    expect(chips.some((chip) => chip.id === 'gate')).toBe(false);
    expect(chips.some((chip) => chip.id === 'hold')).toBe(true);
  });

  it('returns reason chips capped at five', () => {
    const result = sampleResult({
      provider_status: 'critical',
      bar_age_minutes: 90,
      gate_passed: false,
      gate_reason: 'Failed validation',
      readiness_score: 0,
      readiness_band: 'none',
      readiness_hard_stop: true,
      readiness_reason: 'Hard stop: provider is critical and bars are stale over 6 hours.',
    });
    const readiness = computeTradeReadiness(result);
    const chips = readinessReasonChips(result, readiness);
    expect(chips.length).toBeLessThanOrEqual(5);
    expect(chips.some((chip) => chip.label.includes('Provider'))).toBe(true);
  });
});
