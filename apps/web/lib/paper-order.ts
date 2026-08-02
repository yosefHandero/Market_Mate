import { FRESH_BAR_MAX_MINUTES, hasBadFreshnessFlags } from '@/lib/freshness';
import { classifyReadinessState, computeTradeReadiness } from '@/lib/readiness';
import type {
  AutomationStatusResponse,
  DecisionRow,
  OrderPreviewRequest,
  RecommendedAction,
  ScanResult,
} from '@/lib/types';

function rounded(value: number) {
  return Math.round(value * 10_000) / 10_000;
}

export function buildDryRunSetup(result: ScanResult): OrderPreviewRequest {
  const side = 'buy';
  const entry = Math.max(0.01, result.price);
  const qty = Math.max(0.000001, Math.round((100 / entry) * 1_000_000) / 1_000_000);
  const stop = entry * 0.99;
  const target = entry * 1.02;

  return {
    ticker: result.ticker,
    side,
    qty,
    order_type: 'market',
    mode: 'dry_run',
    entry_price: rounded(entry),
    stop_price: rounded(stop),
    target_price: rounded(target),
    recommended_action_snapshot: result.recommended_action ?? null,
  };
}

export function formatPaperSizing(setup: OrderPreviewRequest): {
  notionalLabel: string;
  stopLabel: string;
  targetLabel: string;
} {
  const entry = setup.entry_price ?? 0;
  const notional = entry * setup.qty;
  return {
    notionalLabel: `~$${notional.toFixed(2)} (${setup.qty} @ $${entry.toFixed(2)})`,
    stopLabel: setup.stop_price != null ? `$${setup.stop_price.toFixed(2)}` : '--',
    targetLabel: setup.target_price != null ? `$${setup.target_price.toFixed(2)}` : '--',
  };
}

function selectableAction(action: string | null | undefined): action is 'preview' | 'dry_run' {
  return action === 'preview' || action === 'dry_run';
}

function normalizedProvider(status: string | null | undefined): string {
  return (status ?? '').trim().toLowerCase();
}

export function makeOrderKey(result: ScanResult): string {
  return `dashboard-paper-${result.asset_type}-${result.ticker}-${result.decision_signal.toLowerCase()}-${Date.now()}`;
}

export type PaperActionGate = { allowed: boolean; reason: string; blocked: boolean };

export function evaluatePaperActionGate({
  result,
  decision,
  automation,
}: {
  result: ScanResult;
  decision?: DecisionRow | null;
  automation?: AutomationStatusResponse | null;
}): PaperActionGate {
  const recommendedAction = decision?.recommended_action ?? result.recommended_action ?? null;
  const tradeReadiness = computeTradeReadiness(result, decision ?? null, { automation });
  const readinessState = classifyReadinessState(result, tradeReadiness, decision ?? null, {
    automation,
  });

  const reasons: string[] = [];
  const provider = normalizedProvider(result.provider_status);
  const providerCritical = provider === 'critical' || provider === 'error';
  const barAgeMinutes =
    typeof result.bar_age_minutes === 'number' && Number.isFinite(result.bar_age_minutes)
      ? result.bar_age_minutes
      : null;
  const staleBars = barAgeMinutes !== null && barAgeMinutes > FRESH_BAR_MAX_MINUTES;

  if (automation?.kill_switch_enabled) reasons.push('kill switch is on');
  if (automation?.breaker?.state === 'open') reasons.push('circuit breaker is open');
  if (providerCritical) reasons.push('provider is critical');
  if (staleBars) reasons.push(`bars are stale (${Math.round(barAgeMinutes ?? 0)}m)`);
  if (hasBadFreshnessFlags(result.freshness_flags)) reasons.push('freshness flags are blocking');
  if (tradeReadiness.hardStop) reasons.push('hard stop is active');
  if (result.decision_signal !== 'BUY') {
    reasons.push('only BUY candidates are actionable here');
  }
  if (recommendedAction === 'ignore') {
    reasons.push('ignore is not actionable');
  }
  if (!selectableAction(recommendedAction)) {
    reasons.push('recommended action is not preview or dry-run');
  }
  if (readinessState !== 'ready') {
    reasons.push('setup is not ready');
  }

  const blocked = reasons.length > 0;
  if (blocked) {
    return { allowed: false, reason: `Blocked: ${reasons.join('; ')}.`, blocked: true };
  }
  return {
    allowed: true,
    reason: 'Preview/dry-run allowed by current safety and setup gates.',
    blocked: false,
  };
}

export function recommendedActionLine(
  action: RecommendedAction | null | undefined,
  signal: ScanResult['decision_signal'],
): string {
  if (action === 'dry_run') return 'Dry-run available';
  if (action === 'preview') return 'Preview only';
  if (action === 'review') return 'Review first';
  if (action === 'blocked') return 'Blocked';
  if (action === 'ignore') return 'Ignore';
  if (signal !== 'BUY') return 'Not actionable';
  return 'Review first';
}
