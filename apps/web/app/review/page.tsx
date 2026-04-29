import { JournalEntryForm } from '@/components/journal-entry-form';
import { getJournalEntries, getLatestScan } from '@/lib/api';
import type { RecommendedAction, ScanResult } from '@/lib/types';

function formatEvidenceScore(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? '—' : value.toFixed(2);
}

function resolveRecommendedAction(row: ScanResult): RecommendedAction {
  if (row.recommended_action) {
    return row.recommended_action;
  }
  if (row.decision_signal === 'HOLD') return 'ignore';
  if (row.execution_eligibility === 'eligible') return 'dry_run';
  if (row.execution_eligibility === 'review') return 'review';
  return 'blocked';
}

function actionToneClass(action: RecommendedAction): string {
  if (action === 'dry_run') return 'badge green';
  if (action === 'review' || action === 'preview') return 'badge amber';
  if (action === 'blocked') return 'badge red';
  return 'muted';
}

export default async function ReviewPage() {
  const [latestScanResult, journalEntriesResult] = await Promise.all([
    getLatestScan(),
    getJournalEntries(200),
  ]);

  const hasValidLatestScan = !latestScanResult.error;
  const hasValidJournalEntries =
    !journalEntriesResult.error && Array.isArray(journalEntriesResult.data);
  const run = hasValidLatestScan ? latestScanResult.data : null;
  const entries = hasValidJournalEntries ? journalEntriesResult.data : null;
  const reviewRows =
    hasValidLatestScan && hasValidJournalEntries
      ? (run?.results ?? []).filter((row) => {
          if (row.execution_eligibility !== 'review') return false;
          return entries
            ? !entries.some((entry) => entry.run_id === run?.run_id && entry.ticker === row.ticker)
            : false;
        })
      : null;

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Review Queue</h1>
        <p className="muted" style={{ marginBottom: 16 }}>
          Rows marked <code>review</code> need a human decision before they become useful evidence.
        </p>
        {latestScanResult.error ? <p className="negative">{latestScanResult.error}</p> : null}
        {journalEntriesResult.error ? (
          <p className="negative">
            Review queue unavailable: journal entries could not be loaded.{' '}
            {journalEntriesResult.error}
          </p>
        ) : null}
        {reviewRows?.length ? (
          <div style={{ display: 'grid', gap: 16 }}>
            {reviewRows.map((row) => {
              const recommendedAction = resolveRecommendedAction(row);
              const degradedFreshness = Object.entries(row.freshness_flags ?? {}).filter(
                ([, value]) => value !== 'ok',
              );
              const evidenceLabel = `${row.evidence_quality} (${formatEvidenceScore(
                row.evidence_quality_score,
              )})`;
              const barAge =
                row.bar_age_minutes != null ? `${row.bar_age_minutes.toFixed(1)}m` : '—';

              return (
                <section
                  key={`${run?.run_id}-${row.ticker}`}
                  className="card"
                  style={{ margin: 0 }}
                >
                  <div style={{ marginBottom: 10 }}>
                    <strong>{row.ticker}</strong>
                    <div className="small muted">
                      Signal {row.decision_signal} • Score {row.score.toFixed(1)} • Provider{' '}
                      {row.provider_status}
                    </div>
                    <div className="small muted">
                      Evidence: {evidenceLabel} • Data grade {row.data_grade} • Bar age {barAge}
                    </div>
                    <div className="small" style={{ marginTop: 4 }}>
                      Recommended:{' '}
                      <span className={actionToneClass(recommendedAction)}>
                        {recommendedAction.replace(/_/g, ' ')}
                      </span>
                    </div>
                    {degradedFreshness.length ? (
                      <div className="small negative" style={{ marginTop: 2 }}>
                        Freshness: {degradedFreshness.map(([k, v]) => `${k} ${v}`).join(', ')}
                      </div>
                    ) : null}
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
              );
            })}
          </div>
        ) : reviewRows ? (
          <p className="muted">No review rows are waiting right now.</p>
        ) : null}
      </section>
    </main>
  );
}
