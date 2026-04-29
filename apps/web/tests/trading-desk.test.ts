import { describe, expect, it } from 'vitest';
import {
  buildTickerPriceSeries,
  calculateRiskMetrics,
  deriveInitialOverlay,
} from '@/lib/trading-desk';
import type { PaperPositionSummary, ScanResult, ScanRun } from '@/lib/types';

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
    strategy_version: 'v3',
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

function sampleRun(createdAt: string, results: ScanResult[]): ScanRun {
  return {
    run_id: `run-${createdAt}`,
    created_at: createdAt,
    market_status: 'bullish',
    scan_count: results.length,
    watchlist_size: results.length,
    alerts_sent: 0,
    fear_greed_value: null,
    fear_greed_label: null,
    results,
  };
}

describe('trading desk helpers', () => {
  it('builds a chronological ticker series from scan history and latest scan', () => {
    const older = sampleRun('2026-04-22T17:00:00.000Z', [sampleResult({ price: 98 })]);
    const newer = sampleRun('2026-04-22T17:30:00.000Z', [sampleResult({ price: 99.5 })]);
    const latest = sampleRun('2026-04-22T18:00:00.000Z', [sampleResult({ price: 100.2 })]);

    const points = buildTickerPriceSeries([newer, older], latest, 'AAPL');

    expect(points).toHaveLength(3);
    expect(points.map((point) => point.price)).toEqual([98, 99.5, 100.2]);
  });

  it('derives a sane default long overlay', () => {
    const overlay = deriveInitialOverlay(sampleResult({ price: 125 }));

    expect(overlay.entryPrice).toBe(125);
    expect(overlay.stopLoss).toBeLessThan(overlay.entryPrice);
    expect(overlay.takeProfit).toBeGreaterThan(overlay.entryPrice);
  });

  it('builds fallback price points when a scanner timestamp is invalid', () => {
    const points = buildTickerPriceSeries([], null, 'AAPL');

    expect(points).toEqual([]);

    const fallbackPoints = buildTickerPriceSeries(
      [sampleRun('not-a-date', [sampleResult({ created_at: 'not-a-date' })])],
      null,
      'AAPL',
    );

    expect(fallbackPoints).toHaveLength(12);
    expect(fallbackPoints.every((point) => Number.isFinite(Date.parse(point.timestamp)))).toBe(
      true,
    );
  });

  it('calculates scenario sizing and pnl from the overlay', () => {
    const metrics = calculateRiskMetrics({
      overlay: {
        entryPrice: 100,
        stopLoss: 95,
        takeProfit: 110,
        accountSize: 20_000,
        riskPercent: 1,
      },
      signal: 'BUY',
      triggerPrice: 104,
      paperPositions: [],
      ticker: 'AAPL',
    });

    expect(metrics.rewardMultiple).toBe(2);
    expect(metrics.recommendedPositionSize).toBe(40);
    expect(metrics.openRisk).toBe(200);
    expect(metrics.currentPnl).toBe(160);
    expect(metrics.currentPnlSource).toBe('scenario');
  });

  it('prefers live paper exposure when open positions exist', () => {
    const paperPositions: PaperPositionSummary[] = [
      {
        id: 1,
        intent_key: 'intent-1',
        execution_audit_id: null,
        ticker: 'AAPL',
        asset_type: 'stock',
        side: 'buy',
        quantity: 10,
        simulated_fill_price: 98,
        notional_usd: 980,
        cost_basis_usd: 980,
        close_price: null,
        realized_pnl: null,
        status: 'open',
        opened_at: '2026-04-22T16:00:00.000Z',
        closed_at: null,
        strategy_version: 'v3',
        confidence: 72,
      },
    ];

    const metrics = calculateRiskMetrics({
      overlay: {
        entryPrice: 100,
        stopLoss: 95,
        takeProfit: 110,
        accountSize: 20_000,
        riskPercent: 1,
      },
      signal: 'BUY',
      triggerPrice: 104,
      paperPositions,
      ticker: 'AAPL',
    });

    expect(metrics.totalOpenQuantity).toBe(10);
    expect(metrics.openRisk).toBe(50);
    expect(metrics.currentPnl).toBe(60);
    expect(metrics.currentPnlSource).toBe('paper');
  });
});
