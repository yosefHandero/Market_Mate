import type {
  AutomationStatusResponse,
  DecisionRow,
  DecisionSignal,
  RecommendedAction,
  ScanResult,
} from '@/lib/types';

export type ReadinessTone = 'high' | 'watch' | 'low' | 'none';

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

export type ReadinessFactor = {
  key: ReadinessFactorKey;
  label: string;
  score: number;
  reason: string;
};

export type TradeReadiness = {
  score: number;
  tone: ReadinessTone;
  reason: string;
  action: RecommendedAction | null;
  baseScore: number;
  factors: ReadinessFactor[];
  projection: ReadinessProjection;
  hardStop: boolean;
};

export type TradeReadinessOptions = {
  automation?: AutomationStatusResponse | null;
};

const WEIGHTS: Record<ReadinessFactorKey, number> = {
  signal_confidence: 0.32,
  actionability: 0.18,
  gate_status: 0.16,
  provider_health: 0.14,
  freshness: 0.12,
  risk_setup: 0.08,
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function rounded(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function roundedScore(value: number): number {
  return clamp(Math.round(value), 0, 100);
}

function finitePositive(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

function providerNorm(status: string | null | undefined): string {
  return (status ?? '').trim().toLowerCase();
}

function evidenceNorm(quality: string | null | undefined): string {
  return (quality ?? '').trim().toLowerCase();
}

function actionNorm(action: RecommendedAction | null | undefined): RecommendedAction | null {
  return action ?? null;
}

function isKnownSignal(signal: unknown): signal is DecisionSignal {
  return signal === 'BUY' || signal === 'SELL' || signal === 'HOLD';
}

function isUsablePrice(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function humanizeKey(value: string): string {
  return value.replace(/_/g, ' ');
}

function cleanGateMessage(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed || trimmed.toLowerCase() === 'passed') return null;
  return trimmed;
}

function badFreshnessEntries(
  flags: Record<string, string> | null | undefined,
): Array<[string, string]> {
  if (!flags) return [];
  return Object.entries(flags).filter(([, value]) => value.trim().toLowerCase() !== 'ok');
}

function firstBadFreshnessEntry(
  flags: Record<string, string> | null | undefined,
): [string, string] | null {
  return badFreshnessEntries(flags)[0] ?? null;
}

function selectedAction(result: ScanResult, decision: DecisionRow | null | undefined) {
  return actionNorm(decision?.recommended_action ?? result.recommended_action ?? null);
}

function baseConfidence(result: ScanResult, decision: DecisionRow | null | undefined): number {
  return clamp(
    finitePositive(result.calibrated_confidence) ??
      finitePositive(result.score) ??
      finitePositive(result.raw_score) ??
      finitePositive(decision?.confidence) ??
      finitePositive(decision?.raw_score) ??
      0,
    0,
    100,
  );
}

/** Same geometry as `buildDryRunSetup` in paper-trading-loop (avoid circular import). */
function dryRunPrices(result: ScanResult): {
  entry: number;
  stop: number;
  target: number;
  side: 'buy' | 'sell';
} {
  const side = result.decision_signal === 'SELL' ? 'sell' : 'buy';
  const entry = Math.max(0.01, result.price);
  const stop = side === 'sell' ? entry * 1.01 : entry * 0.99;
  const target = side === 'sell' ? entry * 0.98 : entry * 1.02;
  return {
    entry: rounded(entry),
    stop: rounded(stop),
    target: rounded(target),
    side,
  };
}

function riskStructureValid(
  side: 'buy' | 'sell',
  entry: number,
  stop: number,
  target: number,
): boolean {
  if (side === 'sell') {
    return target <= entry && stop >= entry;
  }
  return target >= entry && stop <= entry;
}

function rewardRiskRatio(side: 'buy' | 'sell', entry: number, stop: number, target: number): number {
  const riskPerUnit = Math.abs(entry - stop);
  const rewardPerUnit = Math.abs(target - entry);
  if (riskPerUnit <= 0) return 0;
  return rewardPerUnit / riskPerUnit;
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

function actionCap(action: RecommendedAction | null): number {
  if (action === 'preview' || action === 'dry_run') return 100;
  if (action === 'review') return 65;
  if (action === 'blocked') return 35;
  if (action === 'ignore') return 30;
  return 40;
}

function actionScore(action: RecommendedAction | null): ReadinessFactor {
  if (action === 'preview' || action === 'dry_run') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 92,
      reason: 'Paper preview or dry-run is selectable.',
    };
  }
  if (action === 'review') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 58,
      reason: 'Review/watch action requires operator judgment first.',
    };
  }
  if (action === 'blocked') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 26,
      reason: 'Trade gate blocked paper action.',
    };
  }
  if (action === 'ignore') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 22,
      reason: 'Ignore means no paper action is currently recommended.',
    };
  }
  return {
    key: 'actionability',
    label: 'Actionability',
    score: 35,
    reason: 'Recommended action is missing.',
  };
}

function gateScore(result: ScanResult, decision: DecisionRow | null | undefined): ReadinessFactor {
  if (result.gate_passed || decision?.gate_passed) {
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 90,
      reason: 'Configured trade gates passed.',
    };
  }
  if (isSampleSizeOnlyBlocked(result)) {
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 28,
      reason: 'Only the sample-size gate is blocking confidence.',
    };
  }
  if (result.decision_signal === 'HOLD') {
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 30,
      reason: 'Gate is not actionable while the signal is HOLD.',
    };
  }
  if (result.gate_passed === false || decision?.gate_passed === false) {
    const failed = failedGateChecks(result)[0];
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 16,
      reason: cleanGateMessage(result.gate_reason) ?? failed?.detail ?? 'One or more gates failed.',
    };
  }
  return {
    key: 'gate_status',
    label: 'Gate status',
    score: 45,
    reason: 'Gate state is unavailable.',
  };
}

function providerScore(status: string): ReadinessFactor {
  if (status === 'ok' || status === 'healthy') {
    return {
      key: 'provider_health',
      label: 'Provider health',
      score: 90,
      reason: 'Provider status is OK.',
    };
  }
  if (status === 'degraded') {
    return {
      key: 'provider_health',
      label: 'Provider health',
      score: 60,
      reason: 'Provider is degraded, but this is a penalty rather than a hard stop.',
    };
  }
  if (status === 'critical' || status === 'error') {
    return {
      key: 'provider_health',
      label: 'Provider health',
      score: 12,
      reason: `Provider status is ${status}.`,
    };
  }
  return {
    key: 'provider_health',
    label: 'Provider health',
    score: 48,
    reason: 'Provider status is unknown.',
  };
}

function freshnessScore(
  flags: Record<string, string> | null | undefined,
  barAgeMinutes: number | null | undefined,
): ReadinessFactor {
  const badEntries = badFreshnessEntries(flags);
  const age = typeof barAgeMinutes === 'number' && Number.isFinite(barAgeMinutes)
    ? barAgeMinutes
    : null;
  let score = 92;
  const reasons: string[] = [];

  if (age != null) {
    if (age > 360) {
      score = Math.min(score, 5);
      reasons.push(`bars ${Math.round(age)}m old`);
    } else if (age > 120) {
      score = Math.min(score, 22);
      reasons.push(`bars ${Math.round(age)}m old`);
    } else if (age > 30) {
      score = Math.min(score, 55);
      reasons.push(`bars ${Math.round(age)}m old`);
    }
  }

  if (badEntries.length) {
    score = Math.max(5, score - badEntries.length * 18);
    const [key, value] = badEntries[0];
    reasons.push(`${humanizeKey(key)}: ${value}`);
  }

  return {
    key: 'freshness',
    label: 'Freshness',
    score,
    reason: reasons.length ? reasons.join(' | ') : 'Data freshness is OK.',
  };
}

function riskScore(result: ScanResult): ReadinessFactor {
  if (!isUsablePrice(result.price) || !isKnownSignal(result.decision_signal)) {
    return {
      key: 'risk_setup',
      label: 'Risk setup',
      score: 0,
      reason: 'Missing a usable price or known signal.',
    };
  }

  const { entry, stop, target, side } = dryRunPrices(result);
  const structureOk = riskStructureValid(side, entry, stop, target);
  if (!structureOk) {
    return {
      key: 'risk_setup',
      label: 'Risk setup',
      score: 30,
      reason: 'Derived stop/target structure is not valid.',
    };
  }

  const rr = rewardRiskRatio(side, entry, stop, target);
  if (rr < 1) {
    return {
      key: 'risk_setup',
      label: 'Risk setup',
      score: 68,
      reason: 'Reward/risk is below 1:1.',
    };
  }

  return {
    key: 'risk_setup',
    label: 'Risk setup',
    score: 88,
    reason: 'Derived paper risk structure is usable.',
  };
}

function signalFactor(baseScore: number, result: ScanResult): ReadinessFactor {
  const eq = evidenceNorm(result.evidence_quality);
  let score = baseScore;
  if (eq === 'low') score = Math.max(0, score - 8);
  else if (eq === 'moderate') score = Math.max(0, score - 3);
  if ((result.evidence_quality_reasons?.length ?? 0) > 2) {
    score = Math.max(0, score - 4);
  }

  return {
    key: 'signal_confidence',
    label: 'Signal confidence',
    score,
    reason:
      baseScore > 0
        ? `Base confidence ${Math.round(baseScore)} from scanner evidence.`
        : 'No positive confidence value was available.',
  };
}

function hardStopReason(
  result: ScanResult,
  provider: string,
  barAgeMinutes: number | null | undefined,
  automation: AutomationStatusResponse | null | undefined,
): string | null {
  if (automation?.kill_switch_enabled) {
    return 'Hard stop: kill switch is active.';
  }
  if (automation?.breaker?.state === 'open') {
    return 'Hard stop: automation circuit breaker is open.';
  }
  if (!isUsablePrice(result.price)) {
    return 'Hard stop: missing or invalid trigger price.';
  }
  if (!isKnownSignal(result.decision_signal)) {
    return 'Hard stop: signal is unknown.';
  }
  const age = typeof barAgeMinutes === 'number' && Number.isFinite(barAgeMinutes)
    ? barAgeMinutes
    : null;
  if ((provider === 'critical' || provider === 'error') && age != null && age > 360) {
    return 'Hard stop: provider is critical and bars are stale over 6 hours.';
  }
  return null;
}

function pickReadinessReason(
  result: ScanResult,
  decision: DecisionRow | null | undefined,
  hardStop: string | null,
): string {
  if (hardStop) return hardStop;

  const action = selectedAction(result, decision);
  const provider = providerNorm(result.provider_status || decision?.provider_status);
  const flags = result.freshness_flags ?? decision?.freshness_flags;
  const barAge = result.bar_age_minutes ?? decision?.bar_age_minutes ?? null;

  if (action === 'blocked' || result.gate_passed === false) {
    if (isSampleSizeOnlyBlocked(result)) {
      return 'Low trust: blocked only by sample size, not by a hard safety stop.';
    }
    const failed = failedGateChecks(result)[0];
    const msg =
      cleanGateMessage(result.gate_reason) ??
      cleanGateMessage(failed?.detail) ??
      'Gate checks did not pass.';
    return `Blocked: ${msg}`;
  }

  if (result.decision_signal === 'HOLD') {
    return 'Low actionability: HOLD signal with usable data.';
  }
  if (action === 'ignore') {
    return 'Low actionability: ignored by recommended action.';
  }
  if (action === 'review') {
    return 'Watch only: review pending.';
  }

  if (provider === 'critical' || provider === 'error') {
    return `Low trust: provider ${provider}.`;
  }
  if (provider === 'degraded') {
    return 'Watch closely: provider is degraded.';
  }

  const staleBars = barAge != null && barAge > 30;
  if (staleBars) {
    return `Stale data: bars ${Math.round(barAge)}m old.`;
  }

  const badFresh = firstBadFreshnessEntry(flags);
  if (badFresh) {
    return `Stale data: ${humanizeKey(badFresh[0])}: ${badFresh[1]}.`;
  }

  return 'Actionable: gates passed and data is fresh.';
}

function pickProjection({
  result,
  action,
  provider,
  freshness,
  hardStop,
  automation,
}: {
  result: ScanResult;
  action: RecommendedAction | null;
  provider: string;
  freshness: ReadinessFactor;
  hardStop: boolean;
  automation?: AutomationStatusResponse | null;
}): ReadinessProjection {
  if (automation?.kill_switch_enabled || automation?.breaker?.state === 'open') {
    return 'kill_switch_or_breaker';
  }
  if (isSampleSizeOnlyBlocked(result)) {
    return 'blocked_until_sample_size';
  }
  if (provider === 'degraded' || provider === 'critical' || provider === 'error' || freshness.score < 60) {
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

function applyFloors({
  score,
  result,
  provider,
  freshness,
  action,
}: {
  score: number;
  result: ScanResult;
  provider: string;
  freshness: ReadinessFactor;
  action: RecommendedAction | null;
}): number {
  let floored = score;
  const nonCriticalProvider = provider !== 'critical' && provider !== 'error';

  if (isUsablePrice(result.price) && isKnownSignal(result.decision_signal) && nonCriticalProvider) {
    floored = Math.max(floored, 8);
  }

  if (
    isSampleSizeOnlyBlocked(result) &&
    freshness.score >= 75 &&
    (provider === 'ok' || provider === 'healthy')
  ) {
    floored = Math.max(floored, 15);
  }

  if (
    (result.decision_signal === 'HOLD' || action === 'ignore') &&
    freshness.score >= 75 &&
    (provider === 'ok' || provider === 'healthy')
  ) {
    floored = Math.max(floored, 12);
  }

  return floored;
}

export function formatReadiness(score: number): string {
  return `${roundedScore(score)}%`;
}

export function readinessTone(score: number): ReadinessTone {
  const s = roundedScore(score);
  if (s >= 70) return 'high';
  if (s >= 40) return 'watch';
  if (s >= 15) return 'low';
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
  const baseScore = baseConfidence(result, decision);
  const provider = providerNorm(result.provider_status || decision?.provider_status);
  const barAge = result.bar_age_minutes ?? decision?.bar_age_minutes ?? null;
  const hardStop = hardStopReason(result, provider, barAge, options?.automation);

  const signal = signalFactor(baseScore, result);
  const actionability = actionScore(action);
  const gate = gateScore(result, decision);
  const providerHealth = providerScore(provider);
  const freshness = freshnessScore(result.freshness_flags ?? decision?.freshness_flags, barAge);
  const risk = riskScore(result);
  const factors: ReadinessFactor[] = [signal, actionability, gate, providerHealth, freshness, risk];

  let score = factors.reduce((sum, factor) => sum + factor.score * WEIGHTS[factor.key], 0);
  score = Math.min(score, actionCap(action));
  if (provider === 'degraded') {
    score = Math.min(score, 80);
  } else if (provider === 'critical' || provider === 'error') {
    score = Math.min(score, 38);
  }
  if (freshness.score < 30) {
    score = Math.min(score, 30);
  }
  score = applyFloors({ score, result, provider, freshness, action });

  if (hardStop) {
    score = 0;
  }

  score = roundedScore(score);
  const projection = pickProjection({
    result,
    action,
    provider,
    freshness,
    hardStop: Boolean(hardStop),
    automation: options?.automation,
  });

  return {
    score,
    tone: readinessTone(score),
    reason: pickReadinessReason(result, decision, hardStop),
    action,
    baseScore: roundedScore(baseScore),
    factors: factors.map((factor) => ({ ...factor, score: roundedScore(factor.score) })),
    projection,
    hardStop: Boolean(hardStop),
  };
}
