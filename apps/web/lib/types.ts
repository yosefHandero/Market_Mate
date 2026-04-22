export type MarketStatus = 'bullish' | 'neutral' | 'bearish';
export type AssetType = 'stock' | 'crypto';
export type DecisionSignal = 'BUY' | 'SELL' | 'HOLD';

export interface GateCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ScanResult {
  ticker: string;
  asset_type: AssetType;
  score: number;
  raw_score: number;
  calibrated_confidence: number;
  calibration_source: string;
  confidence_label: string;
  strategy_id: string;
  strategy_version: string;
  strategy_primary_horizon: string;
  strategy_entry_assumption: string;
  strategy_exit_assumption: string;
  evidence_quality: string;
  evidence_quality_score: number;
  evidence_quality_reasons: string[];
  data_grade: 'decision' | 'research' | 'degraded';
  execution_eligibility: string;
  decision_signal: DecisionSignal;
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
  provider_status: string;
  provider_warnings: string[];
  bar_age_minutes: number | null;
  freshness_flags: Record<string, string>;
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
export type JournalDecision = 'took' | 'skipped' | 'watching';

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
  override_reason: string | null;
  action_state: 'watching' | 'reviewed' | 'took' | 'skipped' | null;
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
  override_reason?: string | null;
  action_state?: 'watching' | 'reviewed' | 'took' | 'skipped' | null;
}
export interface JournalEntryUpdateRequest {
  decision?: JournalDecision;
  entry_price?: number | null;
  exit_price?: number | null;
  pnl_pct?: number | null;
  notes?: string | null;
  override_reason?: string | null;
  action_state?: 'watching' | 'reviewed' | 'took' | 'skipped' | null;
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

export interface DecisionRow {
  symbol: string;
  asset_type: AssetType;
  signal: DecisionSignal;
  confidence: number;
  raw_score: number | null;
  calibration_source: string;
  confidence_label: string;
  evidence_quality: string | null;
  evidence_quality_score: number | null;
  evidence_quality_reasons: string[];
  data_grade: 'decision' | 'research' | 'degraded' | null;
  execution_eligibility: string | null;
  provider_status: string | null;
  gate_passed: boolean | null;
  bar_age_minutes: number | null;
  signal_age_minutes: number | null;
  freshness_flags: Record<string, string> | null;
  recommended_action: 'ignore' | 'review' | 'preview' | 'dry_run' | 'blocked' | null;
  score_contributions: Record<string, number>;
  strategy_version: string | null;
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
  avg_return_after_friction: number | null;
  expectancy_after_friction: number | null;
  false_positive_rate: number | null;
  min_sample_met: boolean;
  is_underpowered: boolean;
}

export interface ValidationSummary {
  generated_at_field?: string;
  start?: string | null;
  end?: string | null;
  primary_horizon: '15m' | '1h' | '1d';
  win_threshold_pct: number;
  false_positive_threshold_pct: number;
  total_signals: number;
  evaluated_count: number;
  pending_count: number;
  overall: ValidationBucket;
  in_sample: ValidationBucket | null;
  out_of_sample: ValidationBucket | null;
  degradation_warnings: string[];
  regime_advisories: string[];
  by_signal: ValidationBucket[];
  by_confidence_bucket: ValidationBucket[];
  by_score_band: ValidationBucket[];
  by_age_bucket: ValidationBucket[];
  by_signal_label: ValidationBucket[];
  by_market_status: ValidationBucket[];
  by_news_source: ValidationBucket[];
  by_volatility_regime: ValidationBucket[];
  by_data_quality: ValidationBucket[];
  by_data_grade: ValidationBucket[];
  by_options_flow_bias: ValidationBucket[];
  by_signal_and_gate: ValidationBucket[];
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
  avg_return_after_friction: number | null;
  expectancy_after_friction: number | null;
  false_positive_rate: number | null;
}

export interface ThresholdSweepResponse {
  generated_at_field?: string;
  start?: string | null;
  end?: string | null;
  primary_horizon: '15m' | '1h' | '1d';
  win_threshold_pct: number;
  false_positive_threshold_pct: number;
  baseline: ValidationBucket;
  by_signal_and_gate: ValidationBucket[];
  recommendation: ThresholdRecommendation;
  candidates: ThresholdSweepRow[];
}

export interface ThresholdRecommendation {
  min_evaluated_count: number;
  min_win_rate: number;
  min_avg_return: number;
  score_band_required: boolean;
  source: 'candidate' | 'configured_fallback';
  evidence_status: 'ready' | 'provisional';
  rationale: string;
  warnings: string[];
}

export interface CohortValidationSummary {
  cohort: string;
  total_signals: number;
  evaluated_count: number;
  pending_count: number;
  win_rate: number | null;
  avg_return: number | null;
  expectancy: number | null;
  avg_return_after_friction: number | null;
  expectancy_after_friction: number | null;
  false_positive_rate: number | null;
  min_sample_met: boolean;
  is_underpowered: boolean;
}

export interface ExecutionAlignmentResponse {
  generated_at_field?: string;
  start?: string | null;
  end?: string | null;
  primary_horizon: '15m' | '1h' | '1d';
  win_threshold_pct: number;
  false_positive_threshold_pct: number;
  all_signals: CohortValidationSummary;
  taken_trades: CohortValidationSummary;
  journal_took?: CohortValidationSummary | null;
  skipped_or_watched: CohortValidationSummary;
  blocked_previews: CohortValidationSummary;
  automation_dry_run?: CohortValidationSummary | null;
}

export interface HealthResponse {
  ok: boolean;
  env: string;
  app_version: string | null;
  ready: boolean;
  live: boolean;
  schema_ok: boolean;
  missing_schema_items: string[];
  scheduler_running: boolean;
  last_scan_at: string | null;
  last_scan_age_minutes: number | null;
  max_stale_minutes: number | null;
  scan_fresh: boolean | null;
  scheduler_enabled: boolean;
  scheduler_interval_seconds: number | null;
  next_scan_due_at: string | null;
  last_scheduler_run_started_at: string | null;
  last_scheduler_run_finished_at: string | null;
  last_scheduler_error: string | null;
  trust_window_start: string | null;
  trust_window_end: string | null;
  trust_recent_window_days: number | null;
  trust_total_signals: number | null;
  trust_evaluated_count: number | null;
  trust_pending_count: number | null;
  trust_buy_passed_evaluated_count: number | null;
  trust_sell_passed_evaluated_count: number | null;
  trust_threshold_evidence_status: string | null;
  trust_threshold_source: string | null;
  trust_threshold_warning_count: number | null;
  trust_evidence_ready: boolean | null;
  pending_due_15m_count: number | null;
  pending_due_1h_count: number | null;
  pending_due_1d_count: number | null;
  request_id: string | null;
}

export interface ExecutionAuditSummary {
  id: number;
  created_at: string;
  updated_at: string;
  ticker: string;
  asset_type: AssetType;
  side: 'buy' | 'sell';
  order_type: 'market' | 'limit';
  qty: number;
  dry_run: boolean;
  lifecycle_status: string;
  latest_price: number | null;
  notional_estimate: number | null;
  signal_outcome_id: number | null;
  signal_run_id: string | null;
  signal_generated_at: string | null;
  latest_signal: DecisionSignal | null;
  confidence: number | null;
  trade_gate_horizon: string | null;
  gate_evaluation_mode: string | null;
  evidence_basis: string | null;
  trust_window_start: string | null;
  trust_window_end: string | null;
  latest_scan_age_minutes: number | null;
  latest_scan_fresh: boolean | null;
  stored_gate_passed: boolean | null;
  stored_gate_reason: string | null;
  gate_consistent_with_signal: boolean | null;
  trade_gate_allowed: boolean | null;
  trade_gate_reason: string | null;
  submitted: boolean;
  broker_order_id: string | null;
  broker_status: string | null;
  error_message: string | null;
}

export interface AutomationIntentSummary {
  id: number;
  created_at: string;
  updated_at: string;
  run_id: string;
  symbol: string;
  asset_type: AssetType;
  side: 'buy' | 'sell';
  qty: number;
  strategy_version: string | null;
  confidence: number | null;
  horizon: string | null;
  status: string;
  status_reason: string | null;
  idempotency_key: string | null;
  execution_audit_id: number | null;
  attempt_count: number;
  request_count_used: number;
  request_count_avoided: number;
  last_attempt_at: string | null;
  next_retry_at: string | null;
  cooldown_until: string | null;
  incident_class: string | null;
}

export interface AutomationBudgetSnapshot {
  hourly_limit: number;
  hourly_used: number;
  daily_limit: number;
  daily_used: number;
  per_symbol_window_limit: number;
  per_symbol_window_seconds: number;
  per_cycle_limit: number;
}

export interface AutomationBreakerSnapshot {
  state: 'closed' | 'open' | 'half_open';
  opened_at: string | null;
  open_until: string | null;
  consecutive_failures: number;
  last_error: string | null;
  probe_owner: string | null;
  probe_expires_at: string | null;
}

export interface AutomationStatusResponse {
  enabled: boolean;
  phase: 'disabled' | 'shadow' | 'limited' | 'broad';
  dry_run_only: boolean;
  kill_switch_enabled: boolean;
  scheduler_triggered: boolean;
  last_processed_run_id: string | null;
  last_processed_run_at: string | null;
  last_recovery_at: string | null;
  requests_made: number;
  requests_avoided: number;
  dedupe_hits: number;
  retries: number;
  blocked_by_budget: number;
  blocked_by_gate: number;
  blocked_by_cooldown: number;
  blocked_by_circuit: number;
  recent_status_counts: Record<string, number>;
  budget: AutomationBudgetSnapshot;
  breaker: AutomationBreakerSnapshot;
  recent_intents: AutomationIntentSummary[];
  candidates_considered: number;
  candidates_reached_execution_call: number;
  filter_rate_pct: number | null;
}

export interface PaperPositionSummary {
  id: number;
  intent_key: string;
  execution_audit_id: number | null;
  ticker: string;
  asset_type: AssetType;
  side: 'buy' | 'sell';
  quantity: number;
  simulated_fill_price: number;
  notional_usd: number;
  cost_basis_usd: number;
  close_price: number | null;
  realized_pnl: number | null;
  status: 'open' | 'closed';
  opened_at: string;
  closed_at: string | null;
  strategy_version: string | null;
  confidence: number | null;
}

export interface PaperLedgerSummary {
  open_positions: number;
  closed_positions: number;
  total_notional_usd: number;
  total_realized_pnl: number;
  total_closed_notional_usd: number;
  long_positions: number;
  short_positions: number;
  last_opened_at: string | null;
  last_closed_at: string | null;
}

export interface ReconciliationIssue {
  kind: string;
  detail: string;
  intent_id: number | null;
  execution_audit_id: number | null;
  paper_position_id: number | null;
}

export interface ReconciliationReportResponse {
  generated_at: string;
  ok: boolean;
  total_issues: number;
  issues: ReconciliationIssue[];
}

export type ConfidenceGrade = 'A' | 'B' | 'C' | 'D';

export interface ProjectionWeek {
  week: number;
  median: number;
  optimistic_p75: number;
  pessimistic_p25: number;
}

export interface ProjectionResponse {
  base_amount: number;
  ticker: string;
  signal: DecisionSignal;
  score_band: string;
  sample_count: number;
  low_sample_size: boolean;
  regime: MarketStatus | null;
  regime_adjusted: boolean;
  projections: ProjectionWeek[];
  confidence_grade: ConfidenceGrade;
  disclaimer: string;
}

export type ActionItemType =
  | 'paper_loop_disabled'
  | 'kill_switch_active'
  | 'breaker_open'
  | 'review_signal'
  | 'watching_entry'
  | 'scheduler_stopped';

export interface ActionItem {
  id: string;
  type: ActionItemType;
  title: string;
  subtitle: string;
  metadata: Record<string, unknown>;
}
