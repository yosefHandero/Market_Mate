import { describe, expect, it } from 'vitest';
import {
  READINESS_BAND_CUTOFFS,
  buildPersonalReview,
  readinessBandForScore,
  type BuildPersonalReviewInput,
} from '@/lib/personal-review';
import { readinessTone } from '@/lib/readiness';
import type {
  ExecutionAuditSummary,
  JournalEntry,
  PaperPositionSummary,
  ValidationSummary,
} from '@/lib/types';

const emptyInput = (): BuildPersonalReviewInput => ({
  validation: null,
  executionAlignment: null,
  paperLedger: [],
  paperLedgerSummary: null,
  journalEntries: [],
  audits: [],
});

function position(overrides: Partial<PaperPositionSummary> = {}): PaperPositionSummary {
  return {
    id: 1,
    intent_key: 'intent-1',
    execution_audit_id: 100,
    ticker: 'AAPL',
    asset_type: 'stock',
    side: 'buy',
    quantity: 1,
    simulated_fill_price: 100,
    notional_usd: 100,
    cost_basis_usd: 100,
    close_price: 120,
    realized_pnl: 20,
    status: 'closed',
    opened_at: '2026-05-01T14:00:00.000Z',
    closed_at: '2026-05-01T15:00:00.000Z',
    strategy_version: 'v4',
    confidence: 75,
    ...overrides,
  };
}

function audit(overrides: Partial<ExecutionAuditSummary> = {}): ExecutionAuditSummary {
  return {
    id: 100,
    created_at: '2026-05-01T14:00:00.000Z',
    updated_at: '2026-05-01T14:01:00.000Z',
    ticker: 'AAPL',
    asset_type: 'stock',
    side: 'buy',
    order_type: 'market',
    qty: 1,
    dry_run: true,
    lifecycle_status: 'previewed',
    latest_price: 100,
    notional_estimate: 100,
    signal_outcome_id: 1,
    signal_run_id: 'run-1',
    signal_generated_at: '2026-05-01T14:00:00.000Z',
    latest_signal: 'BUY',
    confidence: 75,
    trade_gate_horizon: '1h',
    gate_evaluation_mode: 'validation',
    evidence_basis: 'paper',
    trust_window_start: null,
    trust_window_end: null,
    latest_scan_age_minutes: 2,
    latest_scan_fresh: true,
    stored_gate_passed: true,
    stored_gate_reason: 'Passed',
    gate_consistent_with_signal: true,
    trade_gate_allowed: true,
    trade_gate_reason: 'Passed',
    submitted: false,
    broker_order_id: null,
    broker_status: null,
    error_message: null,
    ...overrides,
  };
}

function journal(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 1,
    ticker: 'AAPL',
    run_id: 'run-1',
    decision: 'watching',
    entry_price: 100,
    exit_price: 110,
    pnl_pct: 10,
    notes: '',
    created_at: '2026-05-01T14:02:00.000Z',
    signal_label: 'aggressive',
    score: 75,
    news_source: 'marketaux',
    override_reason: null,
    action_state: 'watching',
    ...overrides,
  };
}

function validation(overrides: Partial<ValidationSummary> = {}): ValidationSummary {
  const bucket = {
    key: 'overall',
    total_signals: 10,
    evaluated_count: 8,
    pending_count: 2,
    win_count: 4,
    loss_count: 4,
    false_positive_count: 1,
    win_rate: 50,
    avg_return: 1.25,
    median_return: 0.5,
    avg_win_return: 3,
    avg_loss_return: -1,
    expectancy: 0.8,
    avg_return_after_friction: 1,
    expectancy_after_friction: 0.6,
    false_positive_rate: 12.5,
    min_sample_met: false,
    is_underpowered: true,
  };

  return {
    primary_horizon: '1h',
    win_threshold_pct: 1,
    false_positive_threshold_pct: -2,
    total_signals: 10,
    evaluated_count: 8,
    pending_count: 2,
    overall: bucket,
    in_sample: null,
    out_of_sample: null,
    degradation_warnings: [],
    regime_advisories: [],
    by_signal: [],
    by_confidence_bucket: [],
    by_score_band: [],
    by_age_bucket: [],
    by_signal_label: [],
    by_market_status: [],
    by_news_source: [],
    by_volatility_regime: [],
    by_data_quality: [],
    by_data_grade: [],
    by_options_flow_bias: [],
    by_signal_and_gate: [],
    by_gate_status: [],
    by_asset_type: [],
    ...overrides,
  };
}

function hasInvalidNumber(value: unknown): boolean {
  if (typeof value === 'number') return !Number.isFinite(value);
  if (Array.isArray(value)) return value.some((item) => hasInvalidNumber(item));
  if (value && typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some((item) => hasInvalidNumber(item));
  }
  return false;
}

describe('personal review helpers', () => {
  it('handles empty data without invalid numbers', () => {
    const review = buildPersonalReview(emptyInput());

    expect(review.baseline.sampleSize).toBe(0);
    expect(review.baseline.winRatePct).toBeNull();
    expect(review.aggregateByReadinessBand).toHaveLength(4);
    expect(review.missedWinsEstimator.estimatedMissedWins).toBe(0);
    expect(hasInvalidNumber(review)).toBe(false);
  });

  it('aggregates a single closed paper row against the baseline', () => {
    const review = buildPersonalReview({
      ...emptyInput(),
      validation: validation(),
      paperLedger: [position()],
      audits: [audit()],
    });

    const high = review.aggregateByReadinessBand.find((row) => row.key === 'high');
    const fresh = review.aggregateByProviderState.find((row) => row.key === 'fresh');

    expect(review.baseline.sampleSize).toBe(1);
    expect(review.baseline.winRatePct).toBe(100);
    expect(review.baseline.avgPnlPct).toBe(20);
    expect(high?.sampleSize).toBe(1);
    expect(high?.baselineSampleSize).toBe(1);
    expect(fresh?.sampleSize).toBe(1);
    expect(review.validationContext?.evaluatedCount).toBe(8);
  });

  it('pins readiness band cutoffs and matches readiness tone boundaries', () => {
    expect(READINESS_BAND_CUTOFFS).toEqual({ high: 70, watch: 50, low: 25 });
    expect(readinessBandForScore(70)).toBe('high');
    expect(readinessBandForScore(50)).toBe('watch');
    expect(readinessBandForScore(25)).toBe('low');
    expect(readinessBandForScore(24)).toBe('none');
    expect(readinessBandForScore(70)).toBe(readinessTone(70));
    expect(readinessBandForScore(50)).toBe(readinessTone(50));
    expect(readinessBandForScore(25)).toBe(readinessTone(25));
    expect(readinessBandForScore(24)).toBe(readinessTone(24));
  });

  it('aggregates by readiness band correctly', () => {
    const review = buildPersonalReview({
      ...emptyInput(),
      paperLedger: [
        position({ id: 1, confidence: 70 }),
        position({ id: 2, confidence: 50, realized_pnl: -5, close_price: 95 }),
        position({ id: 3, confidence: 25, realized_pnl: 0, close_price: 100 }),
        position({ id: 4, confidence: 24, realized_pnl: 4, close_price: 104 }),
      ],
      audits: [audit()],
    });

    const counts = Object.fromEntries(
      review.aggregateByReadinessBand.map((row) => [row.key, row.sampleSize]),
    );

    expect(counts).toEqual({ high: 1, watch: 1, low: 1, none: 1 });
  });

  it('counts blocked-but-watched rows by exact run and ticker', () => {
    const review = buildPersonalReview({
      ...emptyInput(),
      journalEntries: [
        journal({ id: 1, ticker: 'AAPL', run_id: 'run-1', decision: 'watching', pnl_pct: 10 }),
        journal({ id: 2, ticker: 'MSFT', run_id: null, decision: 'watching', pnl_pct: 4 }),
        journal({
          id: 3,
          ticker: 'AAPL',
          run_id: 'run-1',
          decision: 'took',
          action_state: 'took',
          pnl_pct: 12,
        }),
      ],
      audits: [
        audit({
          id: 200,
          ticker: 'AAPL',
          signal_run_id: 'run-1',
          trade_gate_allowed: false,
          stored_gate_passed: false,
        }),
      ],
    });

    expect(review.blockedButWatchedCount).toBe(1);
    expect(review.missedWinsEstimator.estimatedMissedWins).toBe(2);
    expect(review.missedWinsEstimator.blockedButWatchedPositiveCount).toBe(1);
  });
});
