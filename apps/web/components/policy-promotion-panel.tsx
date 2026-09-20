import type { PolicyPromotionReport } from '@/lib/types';

const POLICY_LABELS: Record<string, string> = {
  hybrid_legacy: 'Hybrid (current production)',
  weekly_probability: 'Weekly probability (challenger)',
};

function policyLabel(policyId: string) {
  return POLICY_LABELS[policyId] ?? policyId;
}

function shortFingerprint(value: string | null | undefined) {
  return value ? value.slice(0, 12) : 'unavailable';
}

function exclusionSummary(counts: Record<string, number> | null | undefined) {
  const entries = Object.entries(counts ?? {}).filter(([, value]) => value > 0);
  if (!entries.length) return null;
  return entries
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key.replaceAll('_', ' ')} ${value}`)
    .join('; ');
}

export function PolicyPromotionPanel({ report }: { report: PolicyPromotionReport | null | undefined }) {
  if (!report) return null;

  const flipRequested = report.requested_champion_policy_id !== report.champion_policy_id;
  const flipInEffect = report.effective_champion_policy_id !== report.champion_policy_id;
  const rulerFingerprint = shortFingerprint(report.ruler_fingerprint);
  const exclusions = exclusionSummary(report.pair_exclusion_counts);

  return (
    <section className="card policy-promotion-panel" aria-label="Champion and challenger promotion">
      <h2 className="proof-section-title">Champion vs challenger</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Production serves <strong>{policyLabel(report.effective_champion_policy_id)}</strong>. The
        challenger runs in shadow on the same scans and is judged by the ruler (
        {report.ruler_version}, {rulerFingerprint}). A champion flip executes only when every
        promotion gate clears — no calendar shortcut.
      </p>
      <p
        className={`small ${report.gates_cleared ? 'positive' : 'muted'}`}
        data-testid="policy-promotion-summary"
      >
        {report.summary}
      </p>
      <div className="policy-promotion-checks">
        {report.checks.map((check) => (
          <div
            className="evidence-track-row"
            key={check.name}
            data-testid={`policy-promotion-check-${check.name}`}
          >
            <span className="muted small">{check.name.replaceAll('_', ' ')}</span>
            <strong className={check.passed ? 'positive' : 'negative'}>
              {check.passed ? 'pass' : 'not yet'}
            </strong>
            <span className="muted small">{check.detail}</span>
          </div>
        ))}
      </div>
      <p className="muted small" style={{ margin: '8px 0 0' }} data-testid="policy-promotion-pairs">
        Paired live-shadow comparison: {report.paired_returns_informative} informative pair(s)
        from {report.paired_returns_total} eligible pair(s), with{' '}
        {report.paired_returns_both_abstained} both-abstained, across{' '}
        {report.paired_returns_resolution_clusters} resolution-week cluster(s).
        {report.paired_returns_cluster_metadata_complete
          ? ''
          : ' Resolution-week metadata is incomplete, so promotion remains blocked.'}
      </p>
      <p className="muted small" style={{ margin: '4px 0 0' }} data-testid="policy-promotion-fingerprints">
        Fingerprints: champion {shortFingerprint(report.champion_decision_fingerprint)};
        challenger {shortFingerprint(report.challenger_decision_fingerprint)}.
      </p>
      {exclusions ? (
        <p className="muted small" style={{ margin: '4px 0 0' }} data-testid="policy-promotion-exclusions">
          Excluded evidence: {exclusions}.
        </p>
      ) : null}
      {flipRequested && !flipInEffect ? (
        <p className="small negative" style={{ margin: '4px 0 0' }} data-testid="policy-promotion-blocked">
          Requested champion {policyLabel(report.requested_champion_policy_id)} is not in effect:
          promotion gates have not cleared, so production stays on{' '}
          {policyLabel(report.effective_champion_policy_id)}.
        </p>
      ) : null}
    </section>
  );
}
