export type MarketStatus = 'bullish' | 'neutral' | 'bearish';
export type AssetType = 'stock' | 'crypto';
export type DecisionSignal = 'BUY' | 'SELL' | 'HOLD';
export type RecommendedAction = 'ignore' | 'review' | 'preview' | 'dry_run' | 'blocked';
export type EvidenceGrade = 'Strong' | 'Mixed' | 'Weak';

export interface PricePrediction {
  range_low: number;
  range_high: number;
  horizon: '15m' | '1h' | '1d' | '1w';
  horizon_label: string;
  invalidation: string;
  methodology: string;
  disclaimer: string;
}

export type WeeklyEvidenceBasis =
  | 'historical_only'
  | 'live_forward_proven'
  | 'mixed'
  | 'insufficient';

export interface WeeklyPatternPrediction {
  horizon: '1w';
  horizon_label: string;
  pattern_name: string;
  directional_bias: 'bullish' | 'bearish' | 'neutral';
  range_low: number;
  range_high: number;
  upside_probability_pct?: number | null;
  historical_hit_rate_pct: number | null;
  avg_forward_1w_return_pct: number | null;
  sample_size: number;
  data_quality: 'ok' | 'low' | 'degraded';
  daily_bars_stale?: boolean;
  daily_bars_source?: string;
  forward_days?: number;
  hold_return_tolerance_pct?: number;
  evidence_basis: WeeklyEvidenceBasis;
  real_money_trust_blocked: boolean;
  pattern_gate_checks: GateCheck[];
  methodology: string;
  disclaimer: string;
}

export interface ExitWindow {
  expected_growth_window_label: string;
  expected_growth_days: number;
  estimated_exit_price: number | null;
  projected_range_low: number | null;
  projected_range_high: number | null;
  invalidation_level: number | null;
  invalidation_note: string;
  stop_growing_signal: string;
  stop_growing_conditions: string[];
  risk_warning: string;
  confidence_change_note: string;
  methodology: string;
  disclaimer: string;
}

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
  evidence_grade?: EvidenceGrade;
  top_reasons?: string[];
  price_prediction?: PricePrediction | null;
  weekly_prediction?: WeeklyPatternPrediction | null;
  exit_window?: ExitWindow | null;
  upside_probability_pct?: number | null;
  confidence_score?: number;
  evidence_provenance?: WeeklyEvidenceBasis;
  is_buy_candidate?: boolean;
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
  recommended_action?: RecommendedAction | null;
  gate_passed: boolean;
  gate_reason: string;
  gate_checks: GateCheck[];
  coingecko_price_change_pct_24h: number | null;
  coingecko_market_cap_rank: number | null;
  fear_greed_value: number | null;
  fear_greed_label: string | null;
  provider_status: string;
  provider_warnings: string[];
  price_source?: 'alpaca' | 'coinbase_ws' | 'polygon' | 'stale_cache';
  fallback_used?: boolean;
  bar_age_minutes: number | null;
  freshness_flags: Record<string, string>;
  readiness_score?: number;
  readiness_band?: 'high' | 'watch' | 'low' | 'none';
  readiness_hard_stop?: boolean;
  readiness_reason?: string | null;
  selection_rank?: number | null;
  is_top_pick?: boolean;
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
  top_stocks?: ScanResult[];
  top_crypto?: ScanResult[];
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
  recommended_action: RecommendedAction | null;
  readiness_score?: number | null;
  readiness_band?: 'high' | 'watch' | 'low' | 'none' | null;
  readiness_hard_stop?: boolean | null;
  readiness_reason?: string | null;
  selection_rank?: number | null;
  is_top_pick?: boolean | null;
  rank?: number | null;
  score_contributions: Record<string, number>;
  evidence_grade?: EvidenceGrade | null;
  top_reasons?: string[];
  price_prediction?: PricePrediction | null;
  weekly_prediction?: WeeklyPatternPrediction | null;
  exit_window?: ExitWindow | null;
  upside_probability_pct?: number | null;
  confidence_score?: number | null;
  evidence_provenance?: WeeklyEvidenceBasis | null;
  is_buy_candidate?: boolean | null;
  strategy_version: string | null;
  short_metric_summary: string;
  last_updated: string;
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
  worker_alive?: boolean;
  last_worker_heartbeat_at?: string | null;
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

export interface SystemReadinessAutomation {
  scheduler_enabled: boolean;
  scheduler_running: boolean;
  worker_alive: boolean;
  automation_enabled: boolean;
  automation_phase: 'disabled' | 'shadow' | 'limited' | 'broad';
  automation_ready: boolean;
  dry_run_only: boolean;
  kill_switch_enabled: boolean;
  breaker_state: 'closed' | 'open' | 'half_open' | 'unknown';
}

export interface SystemReadinessProviderSummary {
  worst_status: string;
  total_count: number;
  critical_count: number;
  degraded_count: number;
}

export interface SystemReadinessFreshnessSummary {
  last_scan_at: string | null;
  last_scan_age_minutes: number | null;
  max_stale_minutes: number | null;
  scan_fresh: boolean | null;
  total_count: number;
  stale_count: number;
  severe_stale_count: number;
}

export interface SystemReadinessResponse {
  status: 'PASS' | 'FAIL';
  reasons: string[];
  safety_blockers: string[];
  automation: SystemReadinessAutomation;
  provider: SystemReadinessProviderSummary;
  freshness: SystemReadinessFreshnessSummary;
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

export type OrderSide = 'buy' | 'sell';
export type OrderType = 'market' | 'limit';
export type BrokerName = 'alpaca';

export interface TradeEligibility {
  ticker: string;
  asset_type: AssetType;
  strategy_variant: string;
  requested_side: OrderSide;
  required_signal: DecisionSignal;
  signal_outcome_id: number | null;
  signal_run_id: string | null;
  signal_generated_at: string | null;
  latest_signal: DecisionSignal | null;
  confidence: number | null;
  calibration_source: string | null;
  raw_score: number | null;
  confidence_label: string;
  evidence_quality: string | null;
  evidence_quality_score: number | null;
  evidence_quality_reasons: string[];
  execution_eligibility: string | null;
  strategy_id: string;
  strategy_version: string;
  strategy_primary_horizon: string;
  strategy_entry_assumption: string | null;
  strategy_exit_assumption: string | null;
  signal_age_minutes: number | null;
  confidence_bucket: string | null;
  raw_score_bucket: string | null;
  score_band: string | null;
  horizon: string;
  gate_evaluation_mode: string | null;
  evidence_basis: string | null;
  trust_window_start: string | null;
  trust_window_end: string | null;
  latest_scan_age_minutes: number | null;
  latest_scan_fresh: boolean | null;
  stored_gate_passed: boolean | null;
  stored_gate_reason: string | null;
  gate_consistent_with_signal: boolean | null;
  allowed: boolean;
  reason: string;
  notional_estimate: number;
  qty: number;
  signal_evaluated_count: number | null;
  signal_win_rate: number | null;
  signal_avg_return: number | null;
  score_band_evaluated_count: number | null;
  score_band_win_rate: number | null;
  score_band_avg_return: number | null;
  gate_checks: GateCheck[];
  portfolio_checks: GateCheck[];
  portfolio_summary: string | null;
}

export interface OrderPreviewRequest {
  ticker: string;
  side: OrderSide;
  qty: number;
  order_type?: OrderType;
  limit_price?: number | null;
  preview_audit_id?: number | null;
  idempotency_key?: string | null;
  mode?: 'dry_run' | null;
  entry_price?: number | null;
  stop_price?: number | null;
  target_price?: number | null;
  recommended_action_snapshot?: string | null;
}

export interface OrderPreviewResponse {
  broker: BrokerName;
  ticker: string;
  side: OrderSide;
  qty: number;
  order_type: OrderType;
  notional_estimate: number;
  latest_price: number;
  time_in_force: string;
  warnings: string[];
  trade_gate: TradeEligibility | null;
  execution_audit_id: number | null;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  position_size: number | null;
  estimated_pnl_usd: number | null;
  gate_result: string | null;
  freshness: string | null;
  reject_reasons: string[];
}

export interface OrderPlaceRequest extends OrderPreviewRequest {
  dry_run?: boolean;
}

export interface OrderPlaceResponse {
  ok: boolean;
  broker: BrokerName;
  submitted: boolean;
  dry_run: boolean;
  message: string;
  idempotency_key: string | null;
  order_id: string | null;
  status: string | null;
  raw: Record<string, unknown> | null;
  trade_gate: TradeEligibility | null;
  execution_audit_id: number | null;
  ledger_id: number | null;
  fill_price: number | null;
  filled_qty: number | null;
  slippage_assumption_bps: number | null;
  recommended_action_snapshot: string | null;
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
  total_count: number;
  win_rate_pct: number | null;
  gross_pnl_usd: number;
  max_drawdown_usd: number;
  total_unrealized_pnl?: number | null;
}

export interface ProofLoopMetrics {
  recent_dry_runs: number;
  recent_previewed: number;
  recent_blocked: number;
  total_audits: number;
}

export interface PredictionAccuracyMetrics {
  evaluated_count: number;
  pending_count: number;
  in_range_count: number;
  in_range_rate_pct: number | null;
  below_range_count: number;
  above_range_count: number;
  missed_count: number;
  note: string | null;
}

export interface WeeklyEvidenceProgress {
  live_forward_samples: number;
  out_of_sample_samples: number;
  historical_samples: number;
  backfilled_replay_samples: number;
  min_live_forward_samples: number;
  min_out_of_sample_samples: number;
  min_historical_samples: number;
  min_backfilled_replay_samples: number;
  trust_sample_gate_met: boolean;
  calibration_sample_gate_met: boolean;
}

export interface ConfidenceTierBucket {
  score_band: string;
  asset_type: string;
  signal: string;
  sample_source: string;
  evaluated_count: number;
  win_rate_pct: number | null;
  avg_return_pct: number | null;
  avg_return_after_friction_base_pct: number | null;
  avg_return_after_friction_stressed_pct: number | null;
}

export interface ConfidenceRanking {
  buckets: ConfidenceTierBucket[];
  monotonic_by_group: boolean | null;
  note: string | null;
}

export interface ConfidenceCalibrationBucket {
  probability_band: string;
  asset_type: string;
  evaluated_count: number;
  avg_predicted_pct: number | null;
  realized_up_rate_pct: number | null;
  reliability_gap_pct: number | null;
}

export interface ConfidenceCalibration {
  buckets: ConfidenceCalibrationBucket[];
  mean_abs_reliability_gap_pct: number | null;
  note: string | null;
}

export interface ConfidencePerformance {
  ranking: ConfidenceRanking;
  calibration: ConfidenceCalibration;
}

export interface ExitWindowAssetMetrics {
  asset_type: string;
  evaluated_count: number;
  pending_count: number;
  helped_count: number;
  helped_rate_pct: number | null;
  avg_protected_return_pct: number | null;
  avg_hold_return_pct: number | null;
  avg_protected_after_friction_stressed_pct: number | null;
  avg_hold_after_friction_stressed_pct: number | null;
}

export interface ExitWindowAccuracyMetrics {
  evaluated_count: number;
  pending_count: number;
  helped_count: number;
  helped_rate_pct: number | null;
  by_asset_type: ExitWindowAssetMetrics[];
  note: string | null;
}

export interface WalkForwardAssetMetrics {
  asset_type: string;
  track: string;
  prediction_count: number;
  resolved_count: number;
  pending_count: number;
  upside_hit_rate_pct: number | null;
  avg_return_pct: number | null;
  avg_return_after_friction_pct: number | null;
  avg_return_after_friction_stressed_pct: number | null;
  calibration_mean_abs_gap_pct: number | null;
  exit_window_helped_rate_pct: number | null;
  avg_protected_return_pct: number | null;
  avg_hold_return_pct: number | null;
  worst_return_pct: number | null;
  p05_return_pct: number | null;
  worst_decile_mean_pct: number | null;
  max_drawdown_pct: number | null;
}

export interface WalkForwardCalibrationBucket {
  probability_band: string;
  asset_type: string;
  track: string;
  evaluated_count: number;
  avg_predicted_pct: number | null;
  realized_up_rate_pct: number | null;
  reliability_gap_pct: number | null;
}

export interface WalkForwardCoverageRow {
  symbol: string;
  asset_type: string;
  bar_count: number;
  first_date: string | null;
  last_date: string | null;
  years_available: number;
  source: string;
  sufficient: boolean;
  note: string;
}

// One shared evidence contract: every displayed performance number belongs to
// exactly one of these six canonical tracks. Mirrors app/core/evidence_contract.py.
export type EvidenceTrackKey =
  | 'walk_forward_research'
  | 'walk_forward_holdout'
  | 'historical_replay'
  | 'paper_execution'
  | 'live_forward'
  | 'real_money_pilot';

export interface EvidenceTrackDescriptor {
  key: EvidenceTrackKey;
  label: string;
  description: string;
  is_forward: boolean;
  counts_toward_real_money: boolean;
}

export interface WalkForwardAssetVerdict {
  asset_type: 'stock' | 'crypto';
  ready: boolean;
  real_money_trust_blocked: boolean;
  summary: string;
  checks: GateCheck[];
}

export interface WalkForwardPilotVerdict {
  ready: boolean;
  real_money_trust_blocked: boolean;
  summary: string;
  checks: GateCheck[];
  by_asset?: WalkForwardAssetVerdict[];
}

export interface WalkForwardRunSummary {
  run_id: string;
  created_at: string;
  window_start: string | null;
  window_end: string | null;
  holdout_start: string | null;
  validation_start?: string | null;
  target_years: number;
  step_days: number;
  forward_days: number;
  top_n_per_asset: number;
  symbol_count: number;
  prediction_count: number;
  resolved_count: number;
  pending_count: number;
  evidence_track: string;
  by_asset_track: WalkForwardAssetMetrics[];
  calibration_buckets: WalkForwardCalibrationBucket[];
  coverage: WalkForwardCoverageRow[];
  pilot_verdict: WalkForwardPilotVerdict;
  config_fingerprint?: string | null;
  code_commit?: string | null;
  engine_version?: string | null;
  universe?: string[];
  universe_source?: string | null;
  data_quality_ok?: boolean | null;
  data_quality_issues?: string[];
  survivorship_caveat?: string;
  overlap_status?: string | null;
  note: string | null;
}

export interface LiveForwardAssetProgress {
  asset_type: 'stock' | 'crypto';
  selected: number;
  accepted_outside_top_n: number;
  rejected: number;
  resolved: number;
  pending: number;
  resolved_late: number;
}

export interface LiveForwardProgress {
  campaign_id?: string | null;
  campaign_started_at?: string | null;
  config_fingerprint?: string | null;
  strategy_version?: string | null;
  code_commit?: string | null;
  selected_count: number;
  accepted_outside_top_n_count: number;
  rejected_count: number;
  resolved_count: number;
  pending_count: number;
  resolved_late_count: number;
  by_asset: LiveForwardAssetProgress[];
  last_scan_at?: string | null;
  last_scan_age_minutes?: number | null;
  scan_gap_exceeded: boolean;
  max_expected_scan_gap_minutes?: number | null;
  missed_windows_14d?: number;
  note?: string | null;
}

export interface ProofSummary {
  generated_at: string;
  ledger: PaperLedgerSummary;
  loop_metrics: ProofLoopMetrics;
  prediction_accuracy?: PredictionAccuracyMetrics | null;
  confidence_performance?: ConfidencePerformance | null;
  exit_window_accuracy?: ExitWindowAccuracyMetrics | null;
  weekly_evidence?: WeeklyEvidenceProgress | null;
  walk_forward?: WalkForwardRunSummary | null;
  live_forward?: LiveForwardProgress | null;
  evidence_contract?: EvidenceTrackDescriptor[];
  last_scan_at: string | null;
  scan_fresh: boolean | null;
  mark_prices_source: string;
  note: string | null;
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
