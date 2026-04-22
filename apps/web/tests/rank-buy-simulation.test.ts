import { describe, expect, it, vi } from 'vitest';
import { fetchProjection } from '@/lib/rank-buy-simulation';
import type { ProjectionResponse, ScanResult, ScanRun } from '@/lib/types';

vi.mock('@/lib/scanner-api', () => ({
  fetchScannerJson: vi.fn(),
  getScannerApiBase: () => 'http://localhost:8005',
  getServerReadHeaders: () => ({}),
  readErrorMessage: async () => 'error',
}));

import { fetchScannerJson } from '@/lib/scanner-api';
const mockFetchScannerJson = vi.mocked(fetchScannerJson);

function sampleScanResult(over: Partial<ScanResult> = {}): ScanResult {
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
    strategy_entry_assumption: '',
    strategy_exit_assumption: '',
    evidence_quality: 'high',
    evidence_quality_score: 0.85,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Strong momentum.',
    price: 150,
    price_change_pct: 2.5,
    relative_volume: 1.3,
    relative_strength_pct: 0.6,
    sentiment_score: 0.4,
    filing_flag: false,
    breakout_flag: false,
    market_status: 'neutral',
    sector_strength_score: 0.2,
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
    bar_age_minutes: null,
    freshness_flags: {},
    created_at: '2026-03-20T12:00:00.000Z',
    ...over,
  };
}

function sampleScanRun(results: ScanResult[] = [sampleScanResult()]): ScanRun {
  return {
    run_id: 'run-1',
    created_at: '2026-03-20T12:00:00.000Z',
    market_status: 'neutral',
    scan_count: results.length,
    watchlist_size: results.length,
    alerts_sent: 0,
    fear_greed_value: null,
    fear_greed_label: null,
    results,
  };
}

function sampleProjectionResponse(over: Partial<ProjectionResponse> = {}): ProjectionResponse {
  return {
    base_amount: 100,
    ticker: 'AAPL',
    signal: 'BUY',
    score_band: '60-69',
    sample_count: 35,
    low_sample_size: false,
    regime: 'neutral',
    regime_adjusted: false,
    projections: [
      { week: 1, median: 102.5, optimistic_p75: 105.0, pessimistic_p25: 99.0 },
      { week: 2, median: 104.6, optimistic_p75: 109.2, pessimistic_p25: 98.1 },
      { week: 3, median: 106.3, optimistic_p75: 112.5, pessimistic_p25: 97.4 },
      { week: 4, median: 107.8, optimistic_p75: 115.0, pessimistic_p25: 96.8 },
    ],
    confidence_grade: 'B',
    disclaimer: 'Projection based on historical outcomes of similar signals. Past performance does not guarantee future results.',
    ...over,
  };
}

describe('fetchProjection', () => {
  it('returns error when scan is null', async () => {
    const out = await fetchProjection(1, null);
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error).toMatch(/No scan results/);
  });

  it('returns error when scan has empty results', async () => {
    const out = await fetchProjection(1, sampleScanRun([]));
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error).toMatch(/No scan results/);
  });

  it('returns error for rank 0', async () => {
    const out = await fetchProjection(0, sampleScanRun());
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error).toMatch(/between 1 and/);
  });

  it('returns error for rank exceeding results length', async () => {
    const out = await fetchProjection(5, sampleScanRun());
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error).toMatch(/between 1 and 1/);
  });

  it('returns error for non-integer rank', async () => {
    const out = await fetchProjection(1.5, sampleScanRun());
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error).toMatch(/integer/);
  });

  it('returns projection data from API for valid rank', async () => {
    const response = sampleProjectionResponse();
    mockFetchScannerJson.mockResolvedValueOnce(response);

    const scan = sampleScanRun([sampleScanResult({ raw_score: 68 })]);
    const out = await fetchProjection(1, scan);

    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.result.ticker).toBe('AAPL');
    expect(out.result.projections).toHaveLength(4);
    expect(out.result.confidence_grade).toBe('B');
    expect(mockFetchScannerJson).toHaveBeenCalledWith(
      expect.stringContaining('/scan/projection/AAPL'),
    );
  });

  it('sends correct signal and score_band in query', async () => {
    mockFetchScannerJson.mockResolvedValueOnce(sampleProjectionResponse({ signal: 'SELL' }));

    const scan = sampleScanRun([
      sampleScanResult({ decision_signal: 'SELL', raw_score: 75 }),
    ]);
    const out = await fetchProjection(1, scan);

    expect(out.ok).toBe(true);
    expect(mockFetchScannerJson).toHaveBeenCalledWith(
      expect.stringMatching(/signal=SELL.*score_band=70-79/),
    );
  });

  it('returns error when API call fails', async () => {
    mockFetchScannerJson.mockRejectedValueOnce(new Error('Network timeout'));

    const out = await fetchProjection(1, sampleScanRun());

    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error).toBe('Network timeout');
  });

  it('resolves rank 2 to the second scan result', async () => {
    mockFetchScannerJson.mockResolvedValueOnce(sampleProjectionResponse({ ticker: 'TSLA' }));

    const scan = sampleScanRun([
      sampleScanResult({ ticker: 'AAPL', price: 100 }),
      sampleScanResult({ ticker: 'TSLA', price: 250, raw_score: 82 }),
    ]);
    const out = await fetchProjection(2, scan);

    expect(out.ok).toBe(true);
    expect(mockFetchScannerJson).toHaveBeenCalledWith(
      expect.stringContaining('/scan/projection/TSLA'),
    );
  });
});
