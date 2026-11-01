import type { LiveForwardAssetProgress, LiveForwardProgress } from '@/lib/types';

function AssetRow({ row }: { row: LiveForwardAssetProgress }) {
  return (
    <div
      className="live-forward-asset-row"
      data-testid={`live-forward-asset-${row.asset_type}`}
    >
      <span className="muted small" style={{ textTransform: 'capitalize' }}>
        {row.asset_type}
      </span>
      <span className="small">
        <strong>{row.selected}</strong> selected
      </span>
      <span className="small">
        <strong>{row.accepted_outside_top_n}</strong> accepted&nbsp;(outside top-N)
      </span>
      <span className="small">
        <strong>{row.rejected}</strong> rejected
      </span>
      <span className="small">
        <strong>{row.resolved}</strong> resolved
      </span>
      <span className="small">
        <strong>{row.pending}</strong> pending
        {row.pending_due != null ? ` (${row.pending_due} due)` : ''}
      </span>
      {row.resolved_late > 0 ? (
        <span className="small negative">{row.resolved_late} late</span>
      ) : null}
    </div>
  );
}

export function LiveForwardProgressPanel({
  progress,
}: {
  progress: LiveForwardProgress | null | undefined;
}) {
  return (
    <section
      className="card live-forward-progress-panel"
      aria-label="Live-forward evidence progress"
      data-testid="live-forward-progress-panel"
    >
      <h2 className="proof-section-title">Live-forward evidence progress</h2>

      <div
        className="completion-not-readiness-banner"
        role="note"
        data-testid="completion-not-readiness-banner"
        style={{
          border: '1px solid var(--border, #333)',
          borderRadius: 8,
          padding: '8px 12px',
          margin: '0 0 12px',
        }}
      >
        <strong>Application complete ≠ real-money ready.</strong>{' '}
        <span className="muted small">
          This panel tracks live-forward prediction snapshots. Real-money
          trust is a separate, later decision that depends on the graduation criteria — not on the
          app being finished.
        </span>
      </div>

      {!progress || !progress.campaign_id ? (
        <p className="muted">
          {progress?.note ?? 'No active evidence campaign yet. Progress starts after the next scan.'}
        </p>
      ) : (
        <>
          <div className="live-forward-campaign" data-testid="live-forward-campaign">
            <p className="small" style={{ margin: '0 0 4px' }}>
              Current campaign:{' '}
              <strong>{progress.campaign_id}</strong>
              {progress.strategy_version ? (
                <span className="muted"> · strategy {progress.strategy_version}</span>
              ) : null}
            </p>
            <p className="small" data-testid="live-forward-saved-policy">
              Saved policy: {progress.saved_policy_id ?? 'unknown'} · version{' '}
              {progress.saved_policy_version ?? 'unknown'} · decision{' '}
              {progress.saved_decision_fingerprint?.slice(0, 12) ?? 'unknown'}.
              {' '}Learned artifact {progress.saved_learned_artifacts_fingerprint?.slice(0, 12) ?? 'unknown'}.
            </p>
            <p className="muted small" data-testid="live-forward-runtime-policy">
              API process policy: {progress.runtime_policy_id ?? 'unknown'} · version{' '}
              {progress.runtime_policy_version ?? 'unknown'} · decision{' '}
              {progress.runtime_decision_fingerprint?.slice(0, 12) ?? 'unknown'}.
              {progress.identity_matches_saved_campaign === false
                ? ' Saved campaign and API process identities differ; counts describe the saved campaign.'
                : progress.identity_matches_saved_campaign === true
                  ? ' Matches the saved campaign.'
                  : ' Identity compatibility is unverified.'}
            </p>
            <p className="muted small" style={{ margin: '0 0 8px' }}>
              config {progress.config_fingerprint?.slice(0, 12) ?? '—'}
              {progress.code_commit ? ` · commit ${progress.code_commit.slice(0, 8)}` : ''}
              {progress.campaign_started_at
                ? ` · started ${new Date(progress.campaign_started_at).toLocaleDateString()}`
                : ''}
            </p>
          </div>

          <div className="live-forward-totals" data-testid="live-forward-totals">
            <span className="small">
              <strong>{progress.selected_count}</strong> selected
            </span>
            <span className="small">
              <strong>{progress.accepted_outside_top_n_count}</strong> accepted outside top-N
            </span>
            <span className="small">
              <strong>{progress.rejected_count}</strong> rejected
            </span>
            <span className="small">
              <strong>{progress.resolved_count}</strong> resolved
            </span>
            <span className="small">
              <strong>{progress.pending_count}</strong> pending
            </span>
          </div>
          <p className="muted small">
            Counts cover this campaign only. Selected means stored top-N selection, not an executed paper trade.
            {' '}Prediction-snapshot progress is separate from the signal-return outcomes used by BUY gates.
          </p>
          <p className="muted small" data-testid="live-forward-due">
            {progress.pending_due_count == null
              ? 'Pending-due count unavailable.'
              : `${progress.pending_due_count} pending outcome(s) due now by recorded due time.`}
            {progress.pending_due_count === 0 && progress.pending_count > 0 && !progress.pending_due_unknown_count
              ? ' Pending outcomes are not due yet.' : ''}
            {(progress.pending_due_unknown_count ?? 0) > 0
              ? ` ${progress.pending_due_unknown_count} pending outcome(s) have no recorded due time.` : ''}
          </p>

          <div className="live-forward-assets" style={{ marginTop: 8 }}>
            {progress.by_asset.map((row) => (
              <AssetRow key={row.asset_type} row={row} />
            ))}
          </div>

          {progress.resolved_late_count > 0 ? (
            <p className="negative small" style={{ margin: '8px 0 0' }} data-testid="live-forward-late">
              {progress.resolved_late_count} outcome(s) resolved after their due date.
              Counted, but flagged for reliability review; lateness alone does not identify its cause.
            </p>
          ) : null}

          <p className="muted small" style={{ margin: '8px 0 0' }}>
            Last scan{' '}
            {progress.last_scan_age_minutes != null
              ? `${Math.round(progress.last_scan_age_minutes)} min ago`
              : 'unknown'}
            . Further resolutions can improve or worsen measured results; elapsed time and more rows do not guarantee BUY qualification.
          </p>
        </>
      )}
    </section>
  );
}
