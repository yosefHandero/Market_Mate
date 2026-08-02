import type {
  AutomationStatusResponse,
  DecisionRow,
  HealthResponse,
  PaperLedgerSummary,
  PaperPositionSummary,
  ScanResult,
  ScanRun,
} from '@/lib/types';

export type DashboardFixtureData = {
  latestScan: ScanRun;
  decisions: DecisionRow[];
  automation: AutomationStatusResponse;
  health: HealthResponse;
  paperPositions: PaperPositionSummary[];
  paperSummary: PaperLedgerSummary;
  scanHistory: ScanRun[];
};

const NOW = '2026-05-18T15:00:00.000Z';

export function topResultsByAssetType(
  results: ScanResult[],
  assetType: 'stock' | 'crypto',
  limit = 3,
) {
  return results
    .filter((row) => row.asset_type === assetType && row.is_top_pick)
    .sort((left, right) => (left.selection_rank ?? 999) - (right.selection_rank ?? 999))
    .slice(0, limit);
}

const OFFICIAL_TOP_STOCKS = ['NVDA', 'JPM', 'AAPL'];
const OFFICIAL_TOP_CRYPTO = ['BTC/USD', 'SOL/USD', 'DOGE/USD'];

const READINESS_BY_TICKER: Record<string, Partial<ScanResult>> = {
  NVDA: {
    readiness_score: 92,
    readiness_band: 'high',
    readiness_reason: 'Actionable: gates passed and data is fresh.',
  },
  JPM: {
    readiness_score: 62,
    readiness_band: 'watch',
    readiness_reason: 'Actionable: gates passed and data is fresh.',
  },
  AAPL: {
    readiness_score: 58,
    readiness_band: 'watch',
    readiness_reason: 'Actionable: gates passed and data is fresh.',
  },
  MSFT: {
    readiness_score: 55,
    readiness_band: 'watch',
    readiness_reason: 'Watch only: review pending.',
  },
  TSLA: {
    readiness_score: 21,
    readiness_band: 'low',
    readiness_reason: 'Blocked: Risk gate failed: reward/risk is below the local threshold.',
  },
  ROKU: {
    readiness_score: 0,
    readiness_band: 'none',
    readiness_hard_stop: true,
    readiness_reason: 'Hard stop: provider is critical and bars are stale over 6 hours.',
  },
  'BTC/USD': {
    readiness_score: 88,
    readiness_band: 'high',
    readiness_reason: 'Actionable: gates passed and data is fresh.',
  },
  'ETH/USD': {
    readiness_score: 21,
    readiness_band: 'low',
    readiness_reason: 'Blocked: crypto SELL win rate 41.00% vs required 55.00%.',
  },
  'SOL/USD': {
    readiness_score: 18,
    readiness_band: 'low',
    readiness_reason: 'Low trust: blocked only by sample size, not by a hard safety stop.',
  },
  'DOGE/USD': {
    readiness_score: 12,
    readiness_band: 'low',
    readiness_reason: 'Low actionability: HOLD signal with usable data.',
  },
};

function withOfficialSelection(results: ScanResult[]): ScanResult[] {
  return results.map((result) => {
    const stockRank = OFFICIAL_TOP_STOCKS.indexOf(result.ticker);
    const cryptoRank = OFFICIAL_TOP_CRYPTO.indexOf(result.ticker);
    const selectionRank =
      stockRank >= 0 ? stockRank + 1 : cryptoRank >= 0 ? cryptoRank + 1 : null;
    return {
      ...result,
      ...(READINESS_BY_TICKER[result.ticker] ?? {}),
      selection_rank: selectionRank,
      is_top_pick: selectionRank != null,
    };
  });
}

function scanResult(overrides: Partial<ScanResult>): ScanResult {
  return {
    ticker: 'NVDA',
    asset_type: 'stock',
    score: 90,
    raw_score: 88,
    calibrated_confidence: 90,
    calibration_source: 'fixture',
    confidence_label: 'high_evidence',
    strategy_id: 'scanner-directional',
    strategy_version: 'fixture-v1',
    strategy_primary_horizon: '1h',
    strategy_entry_assumption: 'Break above intraday resistance',
    strategy_exit_assumption: 'Trail into target zone',
    evidence_quality: 'high',
    evidence_quality_score: 0.86,
    evidence_quality_reasons: ['Fixture row with complete evidence.'],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Momentum and relative strength are aligned.',
    price: 100,
    price_change_pct: 2.4,
    relative_volume: 1.6,
    relative_strength_pct: 0.8,
    sentiment_score: 0.25,
    filing_flag: false,
    breakout_flag: true,
    market_status: 'bullish',
    sector_strength_score: 0.7,
    options_flow_score: 0.55,
    options_flow_summary: 'Calls leading with steady volume.',
    options_flow_bullish: true,
    options_call_put_ratio: 1.4,
    alert_sent: false,
    news_checked: true,
    news_source: 'fixture',
    news_cache_label: 'fixture',
    signal_label: 'readiness-fixture',
    data_quality: 'ok',
    volatility_regime: 'normal',
    benchmark_ticker: 'SPY',
    benchmark_change_pct: 0.6,
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
    bar_age_minutes: 6,
    freshness_flags: {},
    readiness_score: 0,
    readiness_band: 'none',
    readiness_hard_stop: false,
    readiness_reason: null,
    selection_rank: null,
    is_top_pick: false,
    created_at: NOW,
    ...overrides,
  };
}

function decisionFromResult(
  result: ScanResult,
  overrides: Partial<DecisionRow> = {},
): DecisionRow {
  return {
    symbol: result.ticker,
    asset_type: result.asset_type,
    signal: result.decision_signal,
    confidence: result.calibrated_confidence,
    raw_score: result.raw_score,
    calibration_source: result.calibration_source,
    confidence_label: result.confidence_label,
    evidence_quality: result.evidence_quality,
    evidence_quality_score: result.evidence_quality_score,
    evidence_quality_reasons: result.evidence_quality_reasons,
    data_grade: result.data_grade,
    execution_eligibility: result.execution_eligibility,
    provider_status: result.provider_status,
    gate_passed: result.gate_passed,
    bar_age_minutes: result.bar_age_minutes,
    signal_age_minutes: Math.max(1, result.bar_age_minutes ?? 1),
    freshness_flags: result.freshness_flags,
    recommended_action: result.recommended_action ?? null,
    readiness_score: result.readiness_score ?? null,
    readiness_band: result.readiness_band ?? null,
    readiness_hard_stop: result.readiness_hard_stop ?? null,
    readiness_reason: result.readiness_reason ?? null,
    selection_rank: result.selection_rank ?? null,
    is_top_pick: result.is_top_pick ?? null,
    score_contributions: {},
    strategy_version: result.strategy_version,
    short_metric_summary: `${result.decision_signal} ${result.strategy_primary_horizon} fixture setup`,
    last_updated: result.created_at,
    ...overrides,
  };
}

function run(
  runId: string,
  createdAt: string,
  results: ScanResult[],
  options: { officialSelection?: boolean } = {},
): ScanRun {
  const officialResults = options.officialSelection
    ? withOfficialSelection(results)
    : results;
  return {
    run_id: runId,
    created_at: createdAt,
    market_status: 'bullish',
    scan_count: officialResults.length,
    watchlist_size: officialResults.length,
    alerts_sent: 0,
    fear_greed_value: 62,
    fear_greed_label: 'Greed',
    results: officialResults,
    top_stocks: options.officialSelection
      ? topResultsByAssetType(officialResults, 'stock')
      : [],
    top_crypto: options.officialSelection
      ? topResultsByAssetType(officialResults, 'crypto')
      : [],
  };
}

const latestResults: ScanResult[] = [
  scanResult({
    ticker: 'NVDA',
    score: 94,
    raw_score: 91,
    calibrated_confidence: 94,
    price: 128.4,
    price_change_pct: 3.15,
    recommended_action: 'preview',
  }),
  scanResult({
    ticker: 'JPM',
    score: 64,
    raw_score: 62,
    calibrated_confidence: 64,
    price: 198.5,
    price_change_pct: 0.55,
    recommended_action: 'preview',
    explanation: 'WATCH-band setup: usable but not top-tier readiness.',
  }),
  scanResult({
    ticker: 'AAPL',
    score: 58,
    raw_score: 56,
    calibrated_confidence: 58,
    price: 211.35,
    price_change_pct: 0.82,
    recommended_action: 'preview',
  }),
  scanResult({
    ticker: 'MSFT',
    score: 76,
    raw_score: 74,
    calibrated_confidence: 76,
    price: 493.2,
    price_change_pct: 1.1,
    recommended_action: 'review',
    explanation: 'Strong setup, but the action still needs operator review.',
  }),
  scanResult({
    ticker: 'TSLA',
    score: 69,
    raw_score: 67,
    calibrated_confidence: 69,
    price: 182.9,
    price_change_pct: -1.35,
    decision_signal: 'SELL',
    recommended_action: 'blocked',
    gate_passed: false,
    gate_reason: 'Risk gate failed: reward/risk is below the local threshold.',
    gate_checks: [
      {
        name: 'risk_reward',
        passed: false,
        detail: 'Reward/risk is below the local threshold.',
      },
    ],
    execution_eligibility: 'blocked',
  }),
  scanResult({
    ticker: 'ROKU',
    score: 86,
    raw_score: 83,
    calibrated_confidence: 86,
    price: 71.4,
    price_change_pct: -2.7,
    recommended_action: 'preview',
    provider_status: 'critical',
    provider_warnings: ['bars_provider_down'],
    bar_age_minutes: 420,
    freshness_flags: { bars: 'stale' },
    explanation: 'System issue: provider is critical and bars are stale.',
  }),
  scanResult({
    ticker: 'BTC/USD',
    asset_type: 'crypto',
    score: 84,
    raw_score: 82,
    calibrated_confidence: 84,
    price: 104250,
    price_change_pct: 1.85,
    coingecko_price_change_pct_24h: 1.85,
    coingecko_market_cap_rank: 1,
    benchmark_ticker: null,
    benchmark_change_pct: null,
    recommended_action: 'preview',
  }),
  scanResult({
    ticker: 'ETH/USD',
    asset_type: 'crypto',
    score: 57,
    raw_score: 55,
    calibrated_confidence: 57,
    price: 3860,
    price_change_pct: -1.6,
    coingecko_price_change_pct_24h: -1.6,
    coingecko_market_cap_rank: 2,
    benchmark_ticker: null,
    benchmark_change_pct: null,
    decision_signal: 'SELL',
    recommended_action: 'blocked',
    gate_passed: false,
    gate_reason: 'Blocked by win_rate: crypto SELL win rate 41.00% vs required 55.00%.',
    gate_checks: [
      {
        name: 'win_rate',
        passed: false,
        detail: 'crypto SELL win rate 41.00% vs required 55.00%.',
      },
    ],
    execution_eligibility: 'blocked',
    explanation: 'Directional SELL with fresh data, but the historical win-rate gate fails.',
  }),
  scanResult({
    ticker: 'SOL/USD',
    asset_type: 'crypto',
    score: 71,
    raw_score: 70,
    calibrated_confidence: 71,
    price: 182.25,
    price_change_pct: 2.2,
    coingecko_price_change_pct_24h: 2.2,
    coingecko_market_cap_rank: 5,
    benchmark_ticker: null,
    benchmark_change_pct: null,
    recommended_action: 'blocked',
    gate_passed: false,
    gate_reason: 'Blocked by sample_size: crypto BUY bucket has 4 1h outcomes; need 20.',
    gate_checks: [
      {
        name: 'sample_size',
        passed: false,
        detail: 'crypto BUY bucket has 4 1h outcomes; need 20.',
      },
    ],
    execution_eligibility: 'blocked',
  }),
  scanResult({
    ticker: 'DOGE/USD',
    asset_type: 'crypto',
    score: 44,
    raw_score: 42,
    calibrated_confidence: 44,
    price: 0.182,
    price_change_pct: -0.9,
    coingecko_price_change_pct_24h: -0.9,
    coingecko_market_cap_rank: 8,
    benchmark_ticker: null,
    benchmark_change_pct: null,
    decision_signal: 'HOLD',
    recommended_action: 'ignore',
    evidence_quality: 'low',
    evidence_quality_score: 0.35,
    evidence_quality_reasons: ['Thin confirmation across inputs.'],
    explanation: 'Hold setup with low evidence.',
  }),
];

const decisions = withOfficialSelection(latestResults).map((result) => decisionFromResult(result));

const scanHistory = [
  run('fixture-history-1', '2026-05-18T11:00:00.000Z', [
    scanResult({
      ticker: 'NVDA',
      score: 52,
      raw_score: 50,
      calibrated_confidence: 52,
      price: 123.1,
      price_change_pct: 0.2,
      created_at: '2026-05-18T11:00:00.000Z',
    }),
  ]),
  run('fixture-history-2', '2026-05-18T12:00:00.000Z', [
    scanResult({
      ticker: 'NVDA',
      score: 64,
      raw_score: 61,
      calibrated_confidence: 64,
      price: 124.6,
      price_change_pct: 0.8,
      created_at: '2026-05-18T12:00:00.000Z',
    }),
  ]),
  run('fixture-history-3', '2026-05-18T13:00:00.000Z', [
    scanResult({
      ticker: 'NVDA',
      score: 73,
      raw_score: 70,
      calibrated_confidence: 73,
      price: 126.2,
      price_change_pct: 1.4,
      created_at: '2026-05-18T13:00:00.000Z',
    }),
  ]),
  run('fixture-history-4', '2026-05-18T14:00:00.000Z', [
    scanResult({
      ticker: 'NVDA',
      score: 88,
      raw_score: 84,
      calibrated_confidence: 88,
      price: 127.5,
      price_change_pct: 2.3,
      created_at: '2026-05-18T14:00:00.000Z',
    }),
  ]),
  run('fixture-latest', NOW, latestResults, { officialSelection: true }),
];

const automation: AutomationStatusResponse = {
  enabled: true,
  phase: 'shadow',
  dry_run_only: true,
  kill_switch_enabled: false,
  scheduler_triggered: true,
  last_processed_run_id: 'fixture-latest',
  last_processed_run_at: NOW,
  last_recovery_at: null,
  requests_made: 0,
  requests_avoided: 9,
  dedupe_hits: 0,
  retries: 0,
  blocked_by_budget: 0,
  blocked_by_gate: 2,
  blocked_by_cooldown: 0,
  blocked_by_circuit: 0,
  recent_status_counts: { preview: 3, blocked: 2, review: 1, ignore: 1 },
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
  candidates_considered: latestResults.length,
  candidates_reached_execution_call: 0,
  filter_rate_pct: 100,
};

const health: HealthResponse = {
  ok: true,
  env: 'local-fixture',
  app_version: 'fixture',
  ready: true,
  live: true,
  schema_ok: true,
  missing_schema_items: [],
  scheduler_running: true,
  worker_alive: true,
  last_worker_heartbeat_at: NOW,
  last_scan_at: NOW,
  last_scan_age_minutes: 4,
  max_stale_minutes: 30,
  scan_fresh: true,
  scheduler_enabled: true,
  scheduler_interval_seconds: 300,
  next_scan_due_at: '2026-05-18T15:05:00.000Z',
  last_scheduler_run_started_at: NOW,
  last_scheduler_run_finished_at: NOW,
  last_scheduler_error: null,
  trust_window_start: '2026-04-18T00:00:00.000Z',
  trust_window_end: NOW,
  trust_recent_window_days: 30,
  trust_total_signals: 120,
  trust_evaluated_count: 84,
  trust_pending_count: 36,
  trust_buy_passed_evaluated_count: 42,
  trust_sell_passed_evaluated_count: 18,
  trust_threshold_evidence_status: 'provisional',
  trust_threshold_source: 'fixture',
  trust_threshold_warning_count: 1,
  trust_evidence_ready: true,
  pending_due_15m_count: 3,
  pending_due_1h_count: 8,
  pending_due_1d_count: 12,
  request_id: 'local-fixture',
};

const paperSummary: PaperLedgerSummary = {
  open_positions: 0,
  closed_positions: 0,
  total_notional_usd: 0,
  total_realized_pnl: 0,
  total_closed_notional_usd: 0,
  long_positions: 0,
  short_positions: 0,
  last_opened_at: null,
  last_closed_at: null,
  total_count: 0,
  win_rate_pct: null,
  gross_pnl_usd: 0,
  max_drawdown_usd: 0,
};

export function getDashboardFixture(): DashboardFixtureData {
  const latestScan = run('fixture-latest', NOW, latestResults, { officialSelection: true });
  return {
    latestScan,
    decisions,
    automation,
    health,
    paperPositions: [],
    paperSummary,
    scanHistory,
  };
}
