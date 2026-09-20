import type { EvidenceTrackDescriptor, WeeklyEvidenceProgress } from '@/lib/types';

/** Map legacy sample_source progress keys onto the shared evidence-contract labels. */
const PROGRESS_LABELS: Record<string, { label: string; trackKey: string }> = {
  live_paper_forward: { label: 'Live-forward', trackKey: 'live_forward' },
  // Held-out live-forward tickers (stored as "out_of_sample" on legacy rows,
  // "live_holdout" on newer rows; the API sums the whole family here).
  out_of_sample: { label: 'Live-forward (live holdout)', trackKey: 'live_forward' },
  historical: { label: 'Walk-forward research', trackKey: 'walk_forward_research' },
  backfilled_replay: { label: 'Historical replay', trackKey: 'historical_replay' },
};

function TrackRow({
  sourceKey,
  samples,
  required,
  kind,
}: {
  sourceKey: string;
  samples: number;
  required: number;
  kind: 'trust' | 'calibration';
}) {
  const met = samples >= required;
  const mapped = PROGRESS_LABELS[sourceKey] ?? { label: sourceKey, trackKey: sourceKey };
  return (
    <div className="evidence-track-row" data-testid={`evidence-track-${kind}-${mapped.trackKey}`}>
      <span className="muted small">{mapped.label}</span>
      <strong className={met ? 'positive' : ''}>
        {samples}/{required}
      </strong>
      <span className="muted small">{met ? 'met' : 'building'}</span>
    </div>
  );
}

function EvidenceContractLegend({ contract }: { contract: EvidenceTrackDescriptor[] }) {
  if (!contract.length) return null;
  return (
    <div className="evidence-contract-legend" data-testid="evidence-contract-legend">
      <p className="small" style={{ margin: '0 0 4px', fontWeight: 600 }}>
        Evidence contract (one shared vocabulary)
      </p>
      <ul className="small" style={{ margin: '0 0 8px', paddingLeft: 16 }}>
        {contract.map((track) => (
          <li key={track.key} data-testid={`evidence-contract-${track.key}`}>
            <strong>{track.label}</strong>
            {track.counts_toward_real_money ? (
              <span className="badge green" style={{ marginLeft: 6 }}>
                counts toward pilot
              </span>
            ) : (
              <span className="badge" style={{ marginLeft: 6 }}>
                context only
              </span>
            )}
            <span className="muted"> — {track.description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EvidenceTracksPanel({
  evidence,
  contract,
}: {
  evidence: WeeklyEvidenceProgress | null | undefined;
  contract?: EvidenceTrackDescriptor[] | null;
}) {
  return (
    <section className="card evidence-tracks-panel" aria-label="Evidence tracks and real-money trust">
      <h2 className="proof-section-title">Evidence tracks and real-money trust</h2>
      <EvidenceContractLegend contract={contract ?? []} />
      {!evidence ? (
        <p className="muted">Evidence progress unavailable.</p>
      ) : (
        <>
          <p className="muted small" style={{ marginTop: 0 }}>
            Real-money trust stays blocked until live-forward evidence clears both sample-count and
            per-candidate performance thresholds. Walk-forward research and historical replay
            support calibration only and never count as live proof.
          </p>
          <div className="evidence-tracks-group">
            <p className="small" style={{ margin: '0 0 4px', fontWeight: 600 }}>
              Live-forward tracks (count toward a future pilot)
            </p>
            <TrackRow
              sourceKey="live_paper_forward"
              samples={evidence.live_forward_samples}
              required={evidence.min_live_forward_samples}
              kind="trust"
            />
            <TrackRow
              sourceKey="out_of_sample"
              samples={evidence.out_of_sample_samples}
              required={evidence.min_out_of_sample_samples}
              kind="trust"
            />
          </div>
          <div className="evidence-tracks-group">
            <p className="small" style={{ margin: '8px 0 4px', fontWeight: 600 }}>
              Calibration tracks (context only)
            </p>
            <TrackRow
              sourceKey="historical"
              samples={evidence.historical_samples}
              required={evidence.min_historical_samples}
              kind="calibration"
            />
            <TrackRow
              sourceKey="backfilled_replay"
              samples={evidence.backfilled_replay_samples}
              required={evidence.min_backfilled_replay_samples}
              kind="calibration"
            />
          </div>
          <p
            className={`small ${evidence.trust_sample_gate_met ? 'muted' : 'negative'}`}
            style={{ margin: '8px 0 0' }}
            data-testid="trust-sample-gate"
          >
            {evidence.trust_sample_gate_met
              ? 'Sample-count gate met. Per-candidate performance and per-pattern checks still apply before real-money trust.'
              : 'Real-money trust blocked: live-forward sample counts are still building.'}
          </p>
        </>
      )}
    </section>
  );
}
