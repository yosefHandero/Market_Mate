import type {
  DecisionRow,
  EvidenceGrade,
  ExitWindow,
  PricePrediction,
  ScanResult,
  WeeklyEvidenceBasis,
  WeeklyPatternPrediction,
} from '@/lib/types';

export type { EvidenceGrade };
export type CardColor = 'green' | 'gray';
export type RiskLevel = 'Low' | 'Moderate' | 'High' | 'Unknown';
export type DataQualityLabel = 'Good' | 'Limited' | 'Degraded' | 'Unknown';

const EVIDENCE_GRADE_MAP: Record<string, EvidenceGrade> = {
  high: 'Strong',
  moderate: 'Mixed',
  low: 'Weak',
  degraded: 'Weak',
  strong: 'Strong',
  mixed: 'Mixed',
  weak: 'Weak',
};

export function evidenceGrade(
  result: ScanResult,
  decision?: DecisionRow | null,
): EvidenceGrade {
  const backendGrade = decision?.evidence_grade ?? result.evidence_grade;
  if (backendGrade && backendGrade in EVIDENCE_GRADE_MAP) {
    return backendGrade as EvidenceGrade;
  }
  if (backendGrade) {
    const normalized = backendGrade.trim();
    if (normalized in EVIDENCE_GRADE_MAP) {
      return EVIDENCE_GRADE_MAP[normalized];
    }
  }
  const quality = (decision?.evidence_quality ?? result.evidence_quality ?? '').trim().toLowerCase();
  if (quality in EVIDENCE_GRADE_MAP) {
    return EVIDENCE_GRADE_MAP[quality];
  }
  const label = (result.signal_label ?? '').trim().toLowerCase();
  if (label === 'strong') return 'Strong';
  if (label === 'watch') return 'Mixed';
  return 'Weak';
}

function humanizeContributionKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function topReasons(
  result: ScanResult,
  decision?: DecisionRow | null,
  limit = 3,
): string[] {
  const backendReasons = decision?.top_reasons?.length
    ? decision.top_reasons
    : result.top_reasons;
  if (backendReasons?.length) {
    return backendReasons.slice(0, limit);
  }

  const reasons: string[] = [];
  const contributions = decision?.score_contributions ?? {};
  const rankedContributions = Object.entries(contributions)
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value) && value !== 0)
    .sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]))
    .map(([key, value]) => `${humanizeContributionKey(key)} (${value > 0 ? '+' : ''}${value.toFixed(1)})`);

  reasons.push(...rankedContributions);

  const evidenceReasons = decision?.evidence_quality_reasons ?? result.evidence_quality_reasons ?? [];
  for (const reason of evidenceReasons) {
    if (reason && !reasons.includes(reason)) {
      reasons.push(reason);
    }
  }

  if (result.explanation?.trim()) {
    reasons.push(result.explanation.trim());
  }

  if (result.gate_reason?.trim() && !result.gate_passed) {
    reasons.push(result.gate_reason.trim());
  }

  const unique = [...new Set(reasons.map((reason) => reason.trim()).filter(Boolean))];
  return unique.slice(0, limit);
}

export function resolvePricePrediction(
  result: ScanResult,
  decision?: DecisionRow | null,
): PricePrediction | null {
  return decision?.price_prediction ?? result.price_prediction ?? null;
}

export function resolveWeeklyPrediction(
  result: ScanResult,
  decision?: DecisionRow | null,
): WeeklyPatternPrediction | null {
  return decision?.weekly_prediction ?? result.weekly_prediction ?? null;
}

export function formatWeeklyPredictionSummary(prediction: WeeklyPatternPrediction | null): string {
  if (!prediction) {
    return 'Weekly pattern prediction unavailable.';
  }
  const hitRate =
    prediction.historical_hit_rate_pct == null
      ? '--'
      : `${prediction.historical_hit_rate_pct.toFixed(1)}%`;
  const avgReturn =
    prediction.avg_forward_1w_return_pct == null
      ? '--'
      : `${prediction.avg_forward_1w_return_pct.toFixed(2)}%`;
  const trustLabel = prediction.real_money_trust_blocked
    ? 'Real-money trust blocked'
    : 'Live-forward evidence sufficient';
  const forwardDays = prediction.forward_days ?? 7;
  const dataQualityLabel = prediction.daily_bars_stale
    ? `${prediction.data_quality} (stale daily bars)`
    : prediction.data_quality;
  const rangeLow = prediction.range_low.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
  });
  const rangeHigh = prediction.range_high.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
  });
  return (
    `Pattern ${prediction.pattern_name} (${prediction.directional_bias}) - ` +
    `${forwardDays}d range ${rangeLow}-${rangeHigh} - ` +
    `hit ${hitRate} - avg 1w ${avgReturn} - n=${prediction.sample_size} - ` +
    `data ${dataQualityLabel} - ${prediction.evidence_basis} - ${trustLabel}`
  );
}

export function formatPredictionRange(prediction: PricePrediction | null): string {
  if (!prediction) {
    return 'Predicted range: unavailable (structural model not attached to this scan).';
  }
  const low = prediction.range_low.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const high = prediction.range_high.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `Predicted range: ${low} - ${high} (structural stop/target, not a guarantee).`;
}

export function formatPredictionHorizon(prediction: PricePrediction | null): string {
  if (!prediction) return 'Horizon: 1 hour (default)';
  return `Horizon: ${prediction.horizon_label || prediction.horizon}`;
}

export function formatPredictionInvalidation(prediction: PricePrediction | null): string {
  if (!prediction) return 'Invalidation: pending structural levels';
  return `Invalidation: ${prediction.invalidation}`;
}

export function riskLevel(result: ScanResult, decision?: DecisionRow | null): RiskLevel {
  const grade = (decision?.data_grade ?? result.data_grade ?? '').trim().toLowerCase();
  const regime = (result.volatility_regime ?? '').trim().toLowerCase();

  if (grade === 'degraded' || regime === 'high' || regime === 'extreme') {
    return 'High';
  }
  if (grade === 'research' || regime === 'elevated') {
    return 'Moderate';
  }
  if (grade === 'decision' && (regime === 'normal' || regime === 'low' || !regime)) {
    return 'Low';
  }
  return 'Unknown';
}

export function cardColor(blocked: boolean): CardColor {
  // Buy-candidate product surface: no BUY/SELL/HOLD color semantics. Blocked candidates
  // are muted; actionable buy candidates use the positive treatment.
  return blocked ? 'gray' : 'green';
}

export function cardColorClass(color: CardColor): string {
  return `decision-card decision-card-${color}`;
}

export function resolveExitWindow(
  result: ScanResult,
  decision?: DecisionRow | null,
): ExitWindow | null {
  return decision?.exit_window ?? result.exit_window ?? null;
}

export function upsideProbability(
  result: ScanResult,
  decision?: DecisionRow | null,
): number | null {
  const value =
    decision?.upside_probability_pct ??
    result.upside_probability_pct ??
    result.weekly_prediction?.upside_probability_pct ??
    decision?.weekly_prediction?.upside_probability_pct ??
    null;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function formatUpsideProbability(
  result: ScanResult,
  decision?: DecisionRow | null,
): string {
  const value = upsideProbability(result, decision);
  if (value == null) return 'Insufficient evidence';
  return `${value.toFixed(0)}%`;
}

export function confidenceScore(
  result: ScanResult,
  decision?: DecisionRow | null,
): number {
  const value =
    decision?.confidence_score ??
    result.confidence_score ??
    decision?.confidence ??
    result.calibrated_confidence ??
    result.score ??
    0;
  return Math.round(typeof value === 'number' && Number.isFinite(value) ? value : 0);
}

const PROVENANCE_LABELS: Record<WeeklyEvidenceBasis, string> = {
  live_forward_proven: 'Live-forward evidence',
  mixed: 'Mixed evidence',
  historical_only: 'Historical-only',
  insufficient: 'Insufficient evidence',
};

export function evidenceProvenance(
  result: ScanResult,
  decision?: DecisionRow | null,
): WeeklyEvidenceBasis {
  return (
    decision?.evidence_provenance ??
    result.evidence_provenance ??
    result.weekly_prediction?.evidence_basis ??
    decision?.weekly_prediction?.evidence_basis ??
    'insufficient'
  );
}

export function provenanceLabel(
  result: ScanResult,
  decision?: DecisionRow | null,
): string {
  return PROVENANCE_LABELS[evidenceProvenance(result, decision)];
}

export function isLiveForwardProven(
  result: ScanResult,
  decision?: DecisionRow | null,
): boolean {
  return evidenceProvenance(result, decision) === 'live_forward_proven';
}

const DATA_QUALITY_LABELS: Record<string, DataQualityLabel> = {
  ok: 'Good',
  low: 'Limited',
  degraded: 'Degraded',
};

export function dataQualityLabel(
  result: ScanResult,
  decision?: DecisionRow | null,
): DataQualityLabel {
  const weekly = resolveWeeklyPrediction(result, decision);
  const key = (weekly?.data_quality ?? result.data_quality ?? '').trim().toLowerCase();
  return DATA_QUALITY_LABELS[key] ?? 'Unknown';
}

function formatCurrencyValue(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatExpectedGrowthWindow(window: ExitWindow | null): string {
  if (!window) return 'Expected growth window: unavailable';
  return `Expected growth window: ${window.expected_growth_window_label}`;
}

export function formatEstimatedExit(window: ExitWindow | null): string {
  if (!window || window.estimated_exit_price == null) {
    return 'Estimated stop-growing point: pending';
  }
  return `Estimated stop-growing point: ${formatCurrencyValue(window.estimated_exit_price)}`;
}

export function formatProjectedRange(window: ExitWindow | null): string {
  if (!window || window.projected_range_low == null || window.projected_range_high == null) {
    return 'Projected range: unavailable';
  }
  return `Projected range: ${formatCurrencyValue(window.projected_range_low)} - ${formatCurrencyValue(
    window.projected_range_high,
  )}`;
}

export function formatInvalidationLevel(window: ExitWindow | null): string {
  if (!window) return 'Invalidation: pending';
  if (window.invalidation_level == null) return `Invalidation: ${window.invalidation_note}`;
  return `Invalidation: ${formatCurrencyValue(window.invalidation_level)} (${window.invalidation_note})`;
}

export function patternName(
  result: ScanResult,
  decision?: DecisionRow | null,
): string {
  const weekly = resolveWeeklyPrediction(result, decision);
  return weekly?.pattern_name ?? 'unclassified';
}

export function decisionScore(result: ScanResult, decision?: DecisionRow | null): number {
  if (typeof result.score === 'number' && Number.isFinite(result.score)) {
    return Math.round(result.score);
  }
  if (typeof decision?.confidence === 'number' && Number.isFinite(decision.confidence)) {
    return Math.round(decision.confidence);
  }
  return 0;
}
