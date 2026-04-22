import { HistoryList } from '@/components/history-list';
import { RankTable } from '@/components/rank-table';
import { getLatestScan, getScanHistory } from '@/lib/api';

export default async function HistoryPage() {
  const [latestScanResult, historyResult] = await Promise.all([
    getLatestScan(),
    getScanHistory(20),
  ]);

  return (
    <main>
      <div className="grid grid-2" style={{ alignItems: 'start', gap: 20 }}>
        <section className="card">
          <h1 style={{ marginBottom: 6 }}>Scan History</h1>
          <p className="muted" style={{ marginBottom: 16 }}>
            Recent runs and top-ranked symbols from each run.
          </p>
          {historyResult.error ? (
            <p className="negative">{historyResult.error}</p>
          ) : historyResult.data?.length ? (
            <HistoryList runs={historyResult.data} />
          ) : (
            <p className="muted">No scan history available yet.</p>
          )}
        </section>

        <section className="card">
          <h2 style={{ marginBottom: 8 }}>Latest scan run</h2>
          {latestScanResult.error ? (
            <p className="negative">{latestScanResult.error}</p>
          ) : latestScanResult.data?.results?.length ? (
            <RankTable results={latestScanResult.data.results} />
          ) : (
            <p className="muted">No ranked rows available yet.</p>
          )}
        </section>
      </div>
    </main>
  );
}
