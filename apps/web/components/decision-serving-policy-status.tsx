import type { PolicyPromotionReport } from '@/lib/types';

const SERVING_POLICY_LABELS: Record<string, string> = {
  hybrid_legacy: 'Baseline policy',
  weekly_probability: 'Weekly probability',
};

export function servingPolicyLabel(policyId: string): string {
  return SERVING_POLICY_LABELS[policyId] ?? policyId;
}

export function DecisionServingPolicyStatus({
  report,
  error,
}: {
  report: PolicyPromotionReport | null | undefined;
  error?: string | null;
}) {
  if (!report) {
    return error ? (
      <p className="decision-policy-status muted small" role="status" data-testid="decision-policy-status">
        Serving policy unavailable.
      </p>
    ) : null;
  }

  const effectiveLabel = servingPolicyLabel(report.effective_champion_policy_id);
  const requestedLabel = servingPolicyLabel(report.requested_champion_policy_id);
  const requestedMismatch =
    report.requested_champion_policy_id !== report.effective_champion_policy_id;

  return (
    <p className="decision-policy-status muted small" role="status" data-testid="decision-policy-status">
      <span>Serving policy: </span>
      <strong>{effectiveLabel}</strong>
      {requestedMismatch ? (
        <span className="decision-policy-mismatch" data-testid="decision-policy-mismatch">
          Requested champion: {requestedLabel}. Effective serving policy remains {effectiveLabel};
          no promotion has occurred.
        </span>
      ) : null}
    </p>
  );
}
