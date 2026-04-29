import { describe, expect, it } from 'vitest';
import {
  buildDecisionPriceMap,
  DEFAULT_SIMULATION_CONFIG,
  simulateDecisionPortfolio,
} from '@/lib/decision-simulation';
import type { DecisionRow, ScanRun } from '@/lib/types';

const sampleRow = (over: Partial<DecisionRow> = {}): DecisionRow => ({
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
  recommended_action: 'review',
  score_contributions: {},
  strategy_version: 'v3',
  short_metric_summary: '—',
  last_updated: '2026-03-20T12:00:00.000Z',
  ...over,
});

describe('simulateDecisionPortfolio', () => {
  it('starts with $500 cash by default', () => {
    const result = simulateDecisionPortfolio([], {});

    expect(result.summary.startingBalance).toBe(DEFAULT_SIMULATION_CONFIG.initialCash);
    expect(result.summary.currentCash).toBe(DEFAULT_SIMULATION_CONFIG.initialCash);
    expect(result.summary.totalEstimatedPortfolioValue).toBe(DEFAULT_SIMULATION_CONFIG.initialCash);
  });

  it('uses 10% of current cash for BUY orders', () => {
    const result = simulateDecisionPortfolio([sampleRow()], { 'STOCK:AAPL': 100 });

    expect(result.rows[0]?.simulatedAction).toBe('buy');
    expect(result.rows[0]?.simulatedOrderValue).toBe(50);
    expect(result.rows[0]?.simulatedQuantity).toBe(0.5);
    expect(result.rows[0]?.postTradeCash).toBe(450);
  });

  it('liquidates 100% of the held quantity on SELL', () => {
    const result = simulateDecisionPortfolio(
      [sampleRow(), sampleRow({ signal: 'SELL' })],
      { 'STOCK:AAPL': 110 },
    );

    expect(result.rows[1]?.simulatedAction).toBe('sell');
    expect(result.rows[1]?.simulatedQuantity).toBe(0.454545);
    expect(result.rows[1]?.postTradePositionQuantity).toBe(0);
    expect(result.summary.currentCash).toBe(500);
    expect(result.summary.openSimulatedPositions).toBe(0);
  });

  it('blocks BUY when cash is below the minimum simulated order value', () => {
    const result = simulateDecisionPortfolio([sampleRow()], { 'STOCK:AAPL': 100 }, { initialCash: 5 });

    expect(result.rows[0]?.simulatedAction).toBe('blocked');
    expect(result.rows[0]?.blockedReason).toContain('minimum simulated order');
    expect(result.summary.currentCash).toBe(5);
  });

  it('blocks SELL when no position exists', () => {
    const result = simulateDecisionPortfolio(
      [sampleRow({ signal: 'SELL' })],
      { 'STOCK:AAPL': 100 },
    );

    expect(result.rows[0]?.simulatedAction).toBe('blocked');
    expect(result.rows[0]?.blockedReason).toContain('No simulated position');
  });

  it('leaves the portfolio unchanged for HOLD rows', () => {
    const result = simulateDecisionPortfolio(
      [sampleRow({ signal: 'HOLD', execution_eligibility: 'not_applicable' })],
      { 'STOCK:AAPL': 100 },
    );

    expect(result.rows[0]?.simulatedAction).toBe('hold');
    expect(result.summary.currentCash).toBe(500);
    expect(result.summary.investedValue).toBe(0);
  });
});

describe('buildDecisionPriceMap', () => {
  it('creates a symbol and asset-type keyed price lookup from the latest scan', () => {
    const scan: ScanRun = {
      run_id: 'run-1',
      created_at: '2026-03-20T12:00:00.000Z',
      market_status: 'neutral',
      scan_count: 1,
      watchlist_size: 1,
      alerts_sent: 0,
      fear_greed_value: null,
      fear_greed_label: null,
      results: [
        {
          ticker: 'AAPL',
          asset_type: 'stock',
          score: 1,
          raw_score: 1,
          calibrated_confidence: 1,
          calibration_source: 'signal',
          confidence_label: 'moderate_evidence',
          strategy_id: 'scanner-directional',
          strategy_version: 'v3',
          strategy_primary_horizon: '1h',
          strategy_entry_assumption: '',
          strategy_exit_assumption: '',
          evidence_quality: 'high',
          evidence_quality_score: 0.8,
          evidence_quality_reasons: [],
          data_grade: 'decision',
          execution_eligibility: 'eligible',
          decision_signal: 'BUY',
          explanation: '',
          price: 123.45,
          price_change_pct: 1.2,
          relative_volume: 1.1,
          relative_strength_pct: 0.5,
          sentiment_score: 0.2,
          filing_flag: false,
          breakout_flag: false,
          market_status: 'neutral',
          sector_strength_score: 0.1,
          options_flow_score: 0,
          options_flow_summary: '',
          options_flow_bullish: false,
          options_call_put_ratio: 0,
          alert_sent: false,
          news_checked: false,
          news_source: 'none',
          news_cache_label: null,
          signal_label: 'moderate',
          data_quality: 'ok',
          volatility_regime: 'normal',
          benchmark_ticker: null,
          benchmark_change_pct: null,
          gate_passed: true,
          gate_reason: '',
          gate_checks: [],
          coingecko_price_change_pct_24h: null,
          coingecko_market_cap_rank: null,
          fear_greed_value: null,
          fear_greed_label: null,
          provider_status: 'ok',
          provider_warnings: [],
          bar_age_minutes: 5,
          freshness_flags: {},
          created_at: '2026-03-20T12:00:00.000Z',
        },
      ],
    };

    expect(buildDecisionPriceMap(scan)).toEqual({ 'STOCK:AAPL': 123.45 });
  });
});
