import { JournalEntryForm } from '@/components/journal-entry-form';
import { getJournalEntries, getLatestScan } from '@/lib/api';
import type { ScanResult } from '@/lib/types';

function formatEvidenceScore(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? '—' : value.toFixed(2);
}

function resolveRecommendedAction(row: ScanResult): string {
  const extra = row as unknown as Record<string, unknown>;
  if (extra.recommended_action && typeof extra.recommended_action === 'string') {
    return extra.recommended_action;
  }
  if ((extra.decision_signal as string) === 'HOLD') return 'ignore';
  if (row.execution_eligibility === 'eligible') return 'dry_run';
  if (row.execution_eligibility === 'review') return 'review';
  return 'blocked';
}

function actionToneClass(action: string): string {
  if (action === 'dry_run') return 'badge green';
  if (action === 'review' || action === 'preview') return 'badge amber';
  if (action === 'blocked') return 'badge red';
  return 'muted';
}

export default async function ReviewPage() {
  const [latestScanResult, entriesResult] = await Promise.all([
    getLatestScan(),
    getJournalEntries(200),
  ]);

  const run = latestScanResult.data;
  const entries = entriesResult.data ?? [];
  const reviewRows = (run?.results ?? []).filter((row) => {
    if (row.execution_eligibility !== 'review') return false;
    return !entries.some((entry) => entry.run_id === run?.run_id && entry.ticker === row.ticker);
  });

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Review Queue</h1>
        <p className="muted" style={{ marginBottom: 16 }}>
          Rows marked <code>review</code> need a human decision before they become useful evidence.
        </p>
        {latestScanResult.error ? (
          <p className="negative">{latestScanResult.error}</p>
        ) : null}
        {reviewRows.length ? (
          <div style={{ display: 'grid', gap: 16 }}>
            {reviewRows.map((row) => (
              <section key={`${run?.run_id}-${row.ticker}`} className="card" style={{ margin: 0 }}>
                <div style={{ marginBottom: 10 }}>
                  <strong>{row.ticker}</strong>
                  <div className="small muted">
                    Signal {(row as unknown as Record<string, unknown>).decision_signal as string ?? row.signal_label} • Score {row.score.toFixed(1)} • Provider {row.provider_status}
                  </div>
                  <div className="small muted">
                    Evidence: {row.evidence_quality} ({formatEvidenceScore(row.evidence_quality_score)}) • Data grade {row.data_grade} • Bar age{' '}
                    {row.bar_age_minutes != null ? `${row.bar_age_minutes.toFixed(1)}m` : '—'}
                  </div>
                  <div className="small" style={{ marginTop: 4 }}>
                    Recommended:{' '}
                    <span className={actionToneClass(resolveRecommendedAction(row))}>
                      {resolveRecommendedAction(row).replace(/_/g, ' ')}
                    </span>
                  </div>
                  {(() => {
                    const degraded = Object.entries(row.freshness_flags ?? {}).filter(
                      ([, v]) => v !== 'ok',
                    );
                    if (!degraded.length) return null;
                    return (
                      <div className="small negative" style={{ marginTop: 2 }}>
                        Freshness: {degraded.map(([k, v]) => `${k} ${v}`).join(', ')}
                      </div>
                    );
                  })()}
                </div>
                <JournalEntryForm
                  defaultTicker={row.ticker}
                  defaultEntryPrice={row.price}
                  defaultRunId={run?.run_id ?? null}
                  defaultSignalLabel={row.signal_label}
                  defaultScore={row.score}
                  defaultNewsSource={row.news_source}
                />
              </section>
            ))}
          </div>
        ) : (
          <p className="muted">No review rows are waiting right now.</p>
        )}
      </section>
    </main>
  );
}
