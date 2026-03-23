export type MarketStatus = "bullish" | "neutral" | "bearish";
export type AssetType = "stock" | "crypto";

export interface GateCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ScanResult {
  ticker: string;
  asset_type: AssetType;
  score: number;
  calibrated_confidence: number;
  calibration_source: string;
  explanation: string;
  price: number;
  price_change_pct: number;
  relative_volume: number;
  relative_strength_pct: number;
  sentiment_score: number;
  filing_flag: boolean;
  breakout_flag: boolean;
  market_status: MarketStatus;
  sector_strength_score: number;
  options_flow_score: number;
  options_flow_summary: string;
  options_flow_bullish: boolean;
  options_call_put_ratio: number;
  alert_sent: boolean;
  news_checked: boolean;
  news_source: string;
  news_cache_label: string | null;
  signal_label: string;
  data_quality: string;
  volatility_regime: string;
  benchmark_ticker: string | null;
  benchmark_change_pct: number | null;
  gate_passed: boolean;
  gate_reason: string;
  gate_checks: GateCheck[];
  coingecko_price_change_pct_24h: number | null;
  coingecko_market_cap_rank: number | null;
  fear_greed_value: number | null;
  fear_greed_label: string | null;
  created_at: string;
}

export interface ScanRun {
  run_id: string;
  created_at: string;
  market_status: MarketStatus;
  scan_count: number;
  watchlist_size: number;
  alerts_sent: number;
  fear_greed_value: number | null;
  fear_greed_label: string | null;
  results: ScanResult[];
}
export type JournalDecision = "took" | "skipped" | "watching";

export interface JournalEntry {
  id: number;
  ticker: string;
  run_id: string | null;
  decision: JournalDecision;
  entry_price: number | null;
  exit_price: number | null;
  pnl_pct: number | null;
  notes: string;
  created_at: string;
  signal_label: string | null;
  score: number | null;
  news_source: string | null;

}

export interface JournalEntryCreateRequest {
  ticker: string;
  run_id: string | null;
  decision: JournalDecision;
  entry_price: number | null;
  exit_price: number | null;
  pnl_pct: number | null;
  notes: string;
  signal_label: string | null;
  score: number | null;
  news_source: string | null;

}
export interface JournalEntryUpdateRequest {
  decision?: JournalDecision;
  entry_price?: number | null;
  exit_price?: number | null;
  pnl_pct?: number | null;
  notes?: string | null;
}
export interface JournalAnalyticsBucket {
  key: string;
  total: number;
  open_count: number;
  closed_count: number;
  win_rate: number | null;
  avg_pnl_pct: number | null;
}

export interface JournalAnalytics {
  total_entries: number;
  took_count: number;
  skipped_count: number;
  watching_count: number;
  open_trades: number;
  closed_trades: number;
  win_rate: number | null;
  avg_pnl_pct: number | null;
  by_signal_label: JournalAnalyticsBucket[];
  by_news_source: JournalAnalyticsBucket[];
  by_ticker: JournalAnalyticsBucket[];
}

export type DecisionSignal = "BUY" | "SELL" | "HOLD";

export interface DecisionRow {
  symbol: string;
  asset_type: AssetType;
  signal: DecisionSignal;
  confidence: number;
  calibration_source: string;
  short_metric_summary: string;
  last_updated: string;
}

export interface ValidationBucket {
  key: string;
  total_signals: number;
  evaluated_count: number;
  pending_count: number;
  win_count: number;
  loss_count: number;
  false_positive_count: number;
  win_rate: number | null;
  avg_return: number | null;
  median_return: number | null;
  avg_win_return: number | null;
  avg_loss_return: number | null;
  expectancy: number | null;
  false_positive_rate: number | null;
}

export interface ValidationSummary {
  primary_horizon: "15m" | "1h" | "1d";
  win_threshold_pct: number;
  false_positive_threshold_pct: number;
  total_signals: number;
  evaluated_count: number;
  pending_count: number;
  overall: ValidationBucket;
  by_signal: ValidationBucket[];
  by_score_band: ValidationBucket[];
  by_signal_label: ValidationBucket[];
  by_market_status: ValidationBucket[];
  by_news_source: ValidationBucket[];
  by_volatility_regime: ValidationBucket[];
  by_data_quality: ValidationBucket[];
  by_options_flow_bias: ValidationBucket[];
  by_gate_status: ValidationBucket[];
  by_asset_type: ValidationBucket[];
}

export interface ThresholdSweepRow {
  min_evaluated_count: number;
  min_win_rate: number;
  min_avg_return: number;
  score_band_required: boolean;
  kept_signals: number;
  blocked_signals: number;
  kept_rate: number;
  win_rate: number | null;
  avg_return: number | null;
  expectancy: number | null;
  false_positive_rate: number | null;
}

export interface ThresholdSweepResponse {
  primary_horizon: "15m" | "1h" | "1d";
  win_threshold_pct: number;
  false_positive_threshold_pct: number;
  baseline: ValidationBucket;
  candidates: ThresholdSweepRow[];
}

export interface CohortValidationSummary {
  cohort: string;
  total_signals: number;
  evaluated_count: number;
  pending_count: number;
  win_rate: number | null;
  avg_return: number | null;
  expectancy: number | null;
  false_positive_rate: number | null;
}

export interface ExecutionAlignmentResponse {
  primary_horizon: "15m" | "1h" | "1d";
  win_threshold_pct: number;
  false_positive_threshold_pct: number;
  all_signals: CohortValidationSummary;
  taken_trades: CohortValidationSummary;
  skipped_or_watched: CohortValidationSummary;
  blocked_previews: CohortValidationSummary;
}