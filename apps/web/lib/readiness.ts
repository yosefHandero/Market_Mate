import type {
  AutomationStatusResponse,
  DecisionRow,
  DecisionSignal,
  RecommendedAction,
  ScanResult,
} from '@/lib/types';

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

export type ReadinessFactor = {
  key: ReadinessFactorKey;
  label: string;
  score: number;
  reason: string;
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

function isProviderCritical(status: string): boolean {
  return status === 'critical' || status === 'error';
}

function isProviderOk(status: string): boolean {
  return status === 'ok' || status === 'healthy';
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
  return Object.entries(flags).filter(([, value]) => String(value).trim().toLowerCase() !== 'ok');
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
      0,
    0,
    100,
  );
}

function baseConfidenceSource(
  result: ScanResult,
  decision: DecisionRow | null | undefined,
): string {
  if (finitePositive(result.calibrated_confidence) != null) return 'calibrated confidence';
  if (finitePositive(result.score) != null) return 'score';
  if (finitePositive(result.raw_score) != null) return 'raw score';
  if (finitePositive(decision?.confidence) != null) return 'decision confidence';
  return 'no positive confidence';
}

function finiteBarAge(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function isFreshData(
  flags: Record<string, string> | null | undefined,
  barAgeMinutes: number | null | undefined,
): boolean {
  const age = finiteBarAge(barAgeMinutes);
  return age != null && age <= 30 && badFreshnessEntries(flags).length === 0;
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

function rewardRiskRatio(
  side: 'buy' | 'sell',
  entry: number,
  stop: number,
  target: number,
): number {
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
      score: 100,
      reason: 'Paper preview or dry-run is selectable.',
    };
  }
  if (action === 'review') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 65,
      reason: 'Review/watch action caps readiness at 65.',
    };
  }
  if (action === 'blocked') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 35,
      reason: 'Blocked action caps readiness at 35.',
    };
  }
  if (action === 'ignore') {
    return {
      key: 'actionability',
      label: 'Actionability',
      score: 30,
      reason: 'Ignore caps readiness at 30.',
    };
  }
  return {
    key: 'actionability',
    label: 'Actionability',
    score: 40,
    reason: 'Missing or unknown action caps readiness at 40.',
  };
}

function gateScore(result: ScanResult, decision: DecisionRow | null | undefined): ReadinessFactor {
  const gateFailed = result.gate_passed === false || decision?.gate_passed === false;

  if (!gateFailed && (result.gate_passed || decision?.gate_passed)) {
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 100,
      reason: 'Configured trade gates passed.',
    };
  }
  if (isSampleSizeOnlyBlocked(result)) {
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 35,
      reason: 'Only the sample-size gate is blocking confidence.',
    };
  }
  if (result.decision_signal === 'HOLD') {
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 35,
      reason: 'Gate is not actionable while the signal is HOLD.',
    };
  }
  if (gateFailed) {
    const failed = failedGateChecks(result)[0];
    return {
      key: 'gate_status',
      label: 'Gate status',
      score: 35,
      reason: cleanGateMessage(result.gate_reason) ?? failed?.detail ?? 'One or more gates failed.',
    };
  }
  return {
    key: 'gate_status',
    label: 'Gate status',
    score: 60,
    reason: 'Gate state is unavailable.',
  };
}

function providerScore(status: string): ReadinessFactor {
  if (isProviderOk(status)) {
    return {
      key: 'provider_health',
      label: 'Provider health',
      score: 100,
      reason: 'Provider status is OK.',
    };
  }
  if (status === 'degraded') {
    return {
      key: 'provider_health',
      label: 'Provider health',
      score: 80,
      reason: 'Provider is degraded, applying a penalty rather than a hard stop.',
    };
  }
  if (isProviderCritical(status)) {
    return {
      key: 'provider_health',
      label: 'Provider health',
      score: 40,
      reason: `Provider status is ${status}.`,
    };
  }
  return {
    key: 'provider_health',
    label: 'Provider health',
    score: 60,
    reason: 'Provider status is unknown.',
  };
}

function freshnessScore(
  flags: Record<string, string> | null | undefined,
  barAgeMinutes: number | null | undefined,
): ReadinessFactor {
  const badEntries = badFreshnessEntries(flags);
  const age = finiteBarAge(barAgeMinutes);
  let score = 100;
  const reasons: string[] = [];

  if (badEntries.length) {
    const penalty = Math.min(badEntries.length * 5, 15);
    score -= penalty;
    const [key, value] = badEntries[0];
    reasons.push(`${badEntries.length} freshness flag${badEntries.length === 1 ? '' : 's'}`);
    reasons.push(`${humanizeKey(key)}: ${value}`);
  }

  if (age != null) {
    if (age > 30) {
      score -= 10;
      reasons.push(`bars ${Math.round(age)}m old`);
    }
    if (age > 120) {
      score = Math.min(score, 30);
    }
    if (age > 1440) {
      score = Math.min(score, 10);
    }
  } else {
    reasons.push('Bar age is unavailable.');
  }

  return {
    key: 'freshness',
    label: 'Freshness',
    score: clamp(score, 0, 100),
    reason: reasons.length ? reasons.join(' | ') : 'Data freshness is OK.',
  };
}

function riskPenalty(result: ScanResult): { penalty: number; reason: string | null } {
  if (!isUsablePrice(result.price) || !isKnownSignal(result.decision_signal)) {
    return {
      penalty: 12,
      reason: 'Risk setup structure is incomplete.',
    };
  }

  const { entry, stop, target, side } = dryRunPrices(result);
  if (!riskStructureValid(side, entry, stop, target)) {
    return {
      penalty: 12,
      reason: 'Derived stop/target structure is not valid.',
    };
  }

  if (rewardRiskRatio(side, entry, stop, target) < 1) {
    return {
      penalty: 4,
      reason: 'Reward/risk is below 1:1.',
    };
  }

  return { penalty: 0, reason: null };
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
      score: 88,
      reason: 'Derived stop/target structure is not valid.',
    };
  }

  const rr = rewardRiskRatio(side, entry, stop, target);
  if (rr < 1) {
    return {
      key: 'risk_setup',
      label: 'Risk setup',
      score: 96,
      reason: 'Reward/risk is below 1:1.',
    };
  }

  return {
    key: 'risk_setup',
    label: 'Risk setup',
    score: 100,
    reason: 'Derived paper risk structure is usable.',
  };
}

function evidencePenalty(
  result: ScanResult,
  decision: DecisionRow | null | undefined,
): {
  penalty: number;
  reasons: string[];
} {
  const eq = evidenceNorm(result.evidence_quality);
  const qualityReasons = result.evidence_quality_reasons?.length
    ? result.evidence_quality_reasons
    : (decision?.evidence_quality_reasons ?? []);
  let penalty = 0;
  const reasons: string[] = [];

  if (eq === 'low') {
    penalty += 8;
    reasons.push('Low evidence quality subtracts 8.');
  } else if (eq === 'moderate') {
    penalty += 2;
    reasons.push('Moderate evidence quality subtracts 2.');
  }
  if (qualityReasons.length > 2) {
    penalty += 4;
    reasons.push('More than two evidence reasons subtracts 4.');
  }

  return { penalty, reasons };
}

function signalFactor(
  baseScore: number,
  result: ScanResult,
  decision: DecisionRow | null | undefined,
): ReadinessFactor {
  const evidence = evidencePenalty(result, decision);
  const score = Math.max(0, baseScore - evidence.penalty);
  const source = baseConfidenceSource(result, decision);

  return {
    key: 'signal_confidence',
    label: 'Signal confidence',
    score,
    reason:
      baseScore > 0
        ? `Base confidence ${Math.round(baseScore)} from ${source}.`
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
  const age = finiteBarAge(barAgeMinutes);
  if (isProviderCritical(provider) && age != null && age > 360) {
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

  if (isProviderCritical(provider)) {
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
  if (provider === 'degraded' || isProviderCritical(provider) || freshness.score < 60) {
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
  action,
  flags,
  barAge,
}: {
  score: number;
  result: ScanResult;
  provider: string;
  action: RecommendedAction | null;
  flags: Record<string, string> | null | undefined;
  barAge: number | null | undefined;
}): number {
  let floored = score;
  const nonCriticalProvider = !isProviderCritical(provider);
  const fresh = isFreshData(flags, barAge);

  if (isUsablePrice(result.price) && nonCriticalProvider) {
    floored = Math.max(floored, 8);
  }

  if (isSampleSizeOnlyBlocked(result) && fresh && isProviderOk(provider)) {
    floored = Math.max(floored, 15);
  }

  if (
    (result.decision_signal === 'HOLD' || action === 'ignore') &&
    fresh &&
    isProviderOk(provider)
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
  if (s >= 50) return 'watch';
  if (s >= 25) return 'low';
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

  const signal = signalFactor(baseScore, result, decision);
  const actionability = actionScore(action);
  const gate = gateScore(result, decision);
  const providerHealth = providerScore(provider);
  const freshness = freshnessScore(result.freshness_flags ?? decision?.freshness_flags, barAge);
  const risk = riskScore(result);
  const factors: ReadinessFactor[] = [signal, actionability, gate, providerHealth, freshness, risk];

  let score = baseScore;
  const reasons: string[] = [];
  const cap = actionCap(action);

  if (score > cap) {
    reasons.push(`Action cap limited readiness to ${cap}.`);
  }
  score = Math.min(score, cap);

  const sampleSizeOnly = isSampleSizeOnlyBlocked(result);
  const gateFailed = result.gate_passed === false || decision?.gate_passed === false;
  if (gateFailed && !sampleSizeOnly) {
    score *= 0.6;
    score = Math.min(score, 35);
    reasons.push('Non-sample-size gate failure applied a 0.6 multiplier and 35 cap.');
  }

  if (isProviderCritical(provider)) {
    score *= 0.4;
    reasons.push(`Provider ${provider || 'critical'} applied a 0.4 multiplier.`);
  } else if (provider === 'degraded') {
    score *= 0.8;
    reasons.push('Provider degraded applied a 0.8 multiplier.');
  }

  const badFreshness = badFreshnessEntries(result.freshness_flags ?? decision?.freshness_flags);
  if (badFreshness.length) {
    const freshnessPenalty = Math.min(badFreshness.length * 5, 15);
    score -= freshnessPenalty;
    reasons.push(
      `${badFreshness.length} freshness flag${badFreshness.length === 1 ? '' : 's'} subtracted ${freshnessPenalty}.`,
    );
  }

  const finiteAge = finiteBarAge(barAge);
  if (finiteAge != null && finiteAge > 30) {
    score -= 10;
    reasons.push(`Bars ${Math.round(finiteAge)}m old subtracted 10.`);
  }
  if (finiteAge != null && finiteAge > 120) {
    score = Math.min(score, 30);
    reasons.push('Bars older than 120m capped readiness at 30.');
  }
  if (finiteAge != null && finiteAge > 1440) {
    score = Math.min(score, 10);
    reasons.push('Bars older than 24h capped readiness at 10.');
  }

  const evidence = evidencePenalty(result, decision);
  if (evidence.penalty > 0) {
    score -= evidence.penalty;
    reasons.push(...evidence.reasons);
  }

  const riskImpact = riskPenalty(result);
  if (riskImpact.penalty > 0) {
    score -= riskImpact.penalty;
    if (riskImpact.reason) reasons.push(`${riskImpact.reason} Subtracted ${riskImpact.penalty}.`);
  }

  score = clamp(score, 0, 100);
  score = applyFloors({
    score,
    result,
    provider,
    action,
    flags: result.freshness_flags ?? decision?.freshness_flags,
    barAge,
  });
  score = Math.min(score, cap);

  if (hardStop) {
    score = 0;
  }

  score = roundedScore(score);
  const tone = readinessTone(score);
  const primaryReason = pickReadinessReason(result, decision, hardStop);
  const allReasons = Array.from(new Set([primaryReason, ...reasons]));
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
    tone,
    band: tone,
    reason: primaryReason,
    reasons: allReasons,
    action,
    baseScore: roundedScore(baseScore),
    factors: factors.map((factor) => ({ ...factor, score: roundedScore(factor.score) })),
    projection,
    hardStop: Boolean(hardStop),
  };
}
