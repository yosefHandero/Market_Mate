import { JournalAnalyticsDashboard } from '@/components/journal-analytics-dashboard';
import { JournalEntryForm } from '@/components/journal-entry-form';
import { JournalList } from '@/components/journal-list';
import { getJournalAnalytics, getJournalEntries, getLatestScan } from '@/lib/api';

export default async function JournalPage() {
  const [entriesResult, analyticsResult, latestScanResult] = await Promise.all([
    getJournalEntries(100),
    getJournalAnalytics(),
    getLatestScan(),
  ]);

  const topResult = latestScanResult.data?.results?.[0];

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Journal</h1>
        <p className="muted" style={{ marginBottom: 16 }}>
          Record trade decisions and review performance by signal cohorts.
        </p>
        <JournalEntryForm
          defaultTicker={topResult?.ticker ?? ''}
          defaultEntryPrice={topResult?.price ?? null}
          defaultRunId={latestScanResult.data?.run_id ?? null}
          defaultSignalLabel={topResult?.signal_label ?? null}
          defaultScore={topResult?.score ?? null}
          defaultNewsSource={topResult?.news_source ?? null}
        />
      </section>

      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Entries</h2>
        {entriesResult.error ? (
          <p className="negative">{entriesResult.error}</p>
        ) : entriesResult.data?.length ? (
          <JournalList entries={entriesResult.data} />
        ) : (
          <p className="muted">No journal entries yet.</p>
        )}
      </section>

      <section>
        {analyticsResult.error ? (
          <div className="card">
            <p className="negative">{analyticsResult.error}</p>
          </div>
        ) : analyticsResult.data ? (
          <JournalAnalyticsDashboard analytics={analyticsResult.data} />
        ) : (
          <div className="card">
            <p className="muted">Journal analytics are not available yet.</p>
          </div>
        )}
      </section>
    </main>
  );
}
