'use client';

import type {
  AutomationStatusResponse,
  DecisionRow,
  RecommendedAction,
  ScanResult,
} from '@/lib/types';
import { FRESH_BAR_MAX_MINUTES } from '@/lib/freshness';

export type ReadinessTone = 'high' | 'watch' | 'low' | 'none';
export type ReadinessBand = ReadinessTone;

export type ReadinessFactorKey =
  | 'signal_confidence'
  | 'actionability'
  | 'gate_status'
  | 'provider_health'
  | 'freshness'
  | 'risk_setup';

export type ReadinessProjection =
  | 'stable'
  | 'improving_possible'
  | 'decaying'
  | 'blocked_until_sample_size'
  | 'kill_switch_or_breaker';

export type ReadinessFactorBucket = 'system' | 'market' | 'safety';

export type ReadinessFactor = {
  key: ReadinessFactorKey;
  label: string;
  score: number;
  reason: string;
  bucket: ReadinessFactorBucket;
};

export type TradeReadiness = {
  score: number;
  tone: ReadinessTone;
  band: ReadinessBand;
  reason: string;
  reasons: string[];
  action: RecommendedAction | null;
  baseScore: number;
  factors: ReadinessFactor[];
  projection: ReadinessProjection;
  hardStop: boolean;
};

export type TradeReadinessOptions = {
  automation?: AutomationStatusResponse | null;
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function roundedScore(value: number): number {
  return clamp(Math.round(value), 0, 100);
}

function providerNorm(status: string | null | undefined): string {
  return (status ?? '').trim().toLowerCase();
}

function isProviderCritical(status: string): boolean {
  return status === 'critical' || status === 'error';
}

function finiteBarAge(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function cleanGateMessage(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed || trimmed.toLowerCase() === 'passed') return null;
  return trimmed;
}

function failedGateChecks(result: ScanResult) {
  return result.gate_checks.filter((check) => !check.passed);
}

function isSampleSizeOnlyBlocked(result: ScanResult): boolean {
  if (result.gate_passed !== false) return false;
  const failed = failedGateChecks(result);
  if (!failed.length) {
    return /sample[_ -]?size/i.test(result.gate_reason);
  }
  return failed.every((check) => /sample[_ -]?size/i.test(`${check.name} ${check.detail}`));
}

function isHoldGateNotApplicable(
  result: ScanResult,
  decision?: DecisionRow | null,
): boolean {
  if (result.decision_signal !== 'HOLD') return false;
  const gateFailed = result.gate_passed === false || decision?.gate_passed === false;
  if (!gateFailed) return false;
  return failedGateChecks(result).length === 0;
}

function selectedAction(result: ScanResult, decision: DecisionRow | null | undefined) {
  return decision?.recommended_action ?? result.recommended_action ?? null;
}

function automationHardStop(
  automation: AutomationStatusResponse | null | undefined,
): string | null {
  if (automation?.kill_switch_enabled) {
    return 'Hard stop: kill switch is active.';
  }
  if (automation?.breaker?.state === 'open') {
    return 'Hard stop: automation circuit breaker is open.';
  }
  return null;
}

function projectionFromBackend(
  result: ScanResult,
  action: RecommendedAction | null,
  provider: string,
  hardStop: boolean,
  automation?: AutomationStatusResponse | null,
): ReadinessProjection {
  if (automation?.kill_switch_enabled || automation?.breaker?.state === 'open') {
    return 'kill_switch_or_breaker';
  }
  if (isSampleSizeOnlyBlocked(result)) {
    return 'blocked_until_sample_size';
  }
  if (provider === 'degraded' || isProviderCritical(provider)) {
    return 'decaying';
  }
  if (action === 'review' || action === 'blocked') {
    return 'improving_possible';
  }
  if (hardStop) {
    return 'decaying';
  }
  return 'stable';
}

export function formatReadiness(score: number): string {
  return `${roundedScore(score)}%`;
}

export function readinessTone(score: number): ReadinessTone {
  const rounded = roundedScore(score);
  if (rounded >= 70) return 'high';
  if (rounded >= 50) return 'watch';
  if (rounded >= 25) return 'low';
  return 'none';
}

export function explainTradeReadiness(
  result: ScanResult,
  decision?: DecisionRow | null,
  options?: TradeReadinessOptions,
): string {
  return computeTradeReadiness(result, decision, options).reason;
}

export function computeTradeReadiness(
  result: ScanResult,
  decision?: DecisionRow | null,
  options?: TradeReadinessOptions,
): TradeReadiness {
  const action = selectedAction(result, decision);
  const automationStop = automationHardStop(options?.automation);
  const backendHardStop = result.readiness_hard_stop ?? false;
  const hardStop = Boolean(automationStop || backendHardStop);
  const score = hardStop ? 0 : roundedScore(result.readiness_score ?? 0);
  const tone = (result.readiness_band ?? readinessTone(score)) as ReadinessTone;
  const reason =
    automationStop ??
    (hardStop && backendHardStop ? result.readiness_reason ?? 'Hard stop is active.' : null) ??
    result.readiness_reason ??
    'Readiness is unavailable from the backend.';
  const provider = providerNorm(result.provider_status || decision?.provider_status);
  const projection = projectionFromBackend(result, action, provider, hardStop, options?.automation);

  return {
    score,
    tone,
    band: tone,
    reason,
    reasons: [reason],
    action,
    baseScore: roundedScore(result.calibrated_confidence || result.score || 0),
    factors: [],
    projection,
    hardStop,
  };
}

export type ReadinessState =
  | 'ready'
  | 'watch'
  | 'review'
  | 'blocked'
  | 'system_issue'
  | 'no_setup'
  | 'sample_size';

export type ReadinessChipTone = 'bad' | 'warning' | 'muted' | 'ok';
export type ReadinessChipBucket = 'system' | 'data' | 'setup';

export type ReadinessReasonChip = {
  id: string;
  label: string;
  tone: ReadinessChipTone;
  bucket: ReadinessChipBucket;
};

export function readinessStateLabel(state: ReadinessState): string {
  switch (state) {
    case 'ready':
      return 'READY';
    case 'watch':
      return 'WATCH';
    case 'review':
      return 'REVIEW';
    case 'blocked':
      return 'SETUP BLOCKED';
    case 'system_issue':
      return 'SYSTEM ISSUE';
    case 'no_setup':
      return 'NO SETUP';
    case 'sample_size':
      return 'SAMPLE SIZE';
    default:
      return 'BLOCKED';
  }
}

export function classifyReadinessState(
  result: ScanResult,
  readiness: TradeReadiness,
  decision?: DecisionRow | null,
  options?: TradeReadinessOptions,
): ReadinessState {
  const automation = options?.automation;
  const provider = providerNorm(result.provider_status || decision?.provider_status);
  const barAge = finiteBarAge(result.bar_age_minutes ?? decision?.bar_age_minutes ?? null);
  const action = readiness.action;

  if (
    automation?.kill_switch_enabled ||
    automation?.breaker?.state === 'open' ||
    readiness.hardStop
  ) {
    return 'system_issue';
  }
  if (isProviderCritical(provider)) return 'system_issue';
  if (barAge != null && barAge > 360) return 'system_issue';

  if (isSampleSizeOnlyBlocked(result)) return 'sample_size';

  if (isHoldGateNotApplicable(result, decision)) return 'no_setup';

  if (result.decision_signal === 'HOLD' || action === 'ignore') {
    if (failedGateChecks(result).length === 0) {
      return 'no_setup';
    }
  }

  const gateFailed = result.gate_passed === false || decision?.gate_passed === false;
  if (gateFailed && !isSampleSizeOnlyBlocked(result)) return 'blocked';
  if (action === 'review') return 'review';

  if (readiness.score >= 70 && (action === 'preview' || action === 'dry_run')) return 'ready';
  if (readiness.score >= 50 && !readiness.hardStop) return 'watch';
  if (action === 'blocked') return 'blocked';

  return readiness.score >= 25 ? 'review' : 'blocked';
}

export function readinessReasonChips(
  result: ScanResult,
  readiness: TradeReadiness,
  decision?: DecisionRow | null,
  options?: TradeReadinessOptions,
): ReadinessReasonChip[] {
  const chips: ReadinessReasonChip[] = [];
  const automation = options?.automation;
  const provider = providerNorm(result.provider_status || decision?.provider_status);
  const barAge = finiteBarAge(result.bar_age_minutes ?? decision?.bar_age_minutes ?? null);
  const action = readiness.action;

  if (automation?.kill_switch_enabled) {
    chips.push({ id: 'kill-switch', label: 'Kill switch', tone: 'bad', bucket: 'system' });
  }
  if (automation?.breaker?.state === 'open') {
    chips.push({ id: 'breaker', label: 'Breaker open', tone: 'bad', bucket: 'system' });
  }
  if (isProviderCritical(provider)) {
    chips.push({ id: 'provider', label: 'Provider critical', tone: 'bad', bucket: 'system' });
  } else if (provider === 'degraded') {
    chips.push({ id: 'provider', label: 'Provider degraded', tone: 'warning', bucket: 'system' });
  }
  if (barAge != null && barAge > FRESH_BAR_MAX_MINUTES) {
    chips.push({
      id: 'bars',
      label: `Bars ${Math.round(barAge)}m stale`,
      tone: barAge > 120 ? 'bad' : 'warning',
      bucket: 'data',
    });
  }
  if (result.gate_passed === false || decision?.gate_passed === false) {
    if (isSampleSizeOnlyBlocked(result)) {
      chips.push({ id: 'sample-size', label: 'Sample size only', tone: 'warning', bucket: 'data' });
    } else if (!isHoldGateNotApplicable(result, decision)) {
      const gateMsg =
        cleanGateMessage(result.gate_reason) ??
        cleanGateMessage(failedGateChecks(result)[0]?.detail) ??
        'Gate blocked';
      chips.push({
        id: 'gate',
        label: gateMsg.length > 28 ? `${gateMsg.slice(0, 25)}...` : gateMsg,
        tone: 'bad',
        bucket: 'setup',
      });
    }
  }
  if (result.decision_signal === 'HOLD') {
    chips.push({ id: 'hold', label: 'Signal HOLD', tone: 'muted', bucket: 'setup' });
  }
  if (action === 'review') {
    chips.push({ id: 'review', label: 'Action: review', tone: 'warning', bucket: 'setup' });
  }
  const eq = (result.evidence_quality ?? '').trim().toLowerCase();
  if (eq === 'low') {
    chips.push({ id: 'evidence', label: 'Evidence low', tone: 'warning', bucket: 'data' });
  } else if (eq === 'moderate') {
    chips.push({ id: 'evidence', label: 'Evidence moderate', tone: 'muted', bucket: 'data' });
  }

  const seen = new Set<string>();
  return chips
    .filter((chip) => {
      if (seen.has(chip.id)) return false;
      seen.add(chip.id);
      return true;
    })
    .slice(0, 5);
}
