import { ActionList } from '@/components/action-list';
import { OperatorActions } from '@/components/operator-actions';
import { RankBuySimulationPanel } from '@/components/rank-buy-simulation-panel';
import { RankTable } from '@/components/rank-table';
import { GemmaTestButton } from '@/components/gemma-test-button';

import {
  getAutomationStatus,
  getJournalEntries,
  getLatestDecisions,
  getLatestScan,
  getReadyz,
} from '@/lib/api';
import { computePendingActions } from '@/lib/actions';

export default async function HomePage() {
  const [decisionsResult, automationResult, journalResult, healthResult, latestScanResult] =
    await Promise.all([
      getLatestDecisions(),
      getAutomationStatus(),
      getJournalEntries(200),
      getReadyz(),
      getLatestScan(),
    ]);

  const items = computePendingActions({
    decisions: decisionsResult.data,
    automation: automationResult.data,
    journalEntries: journalResult.data,
    health: healthResult.data,
    latestScan: latestScanResult.data,
  });

  const errors = [
    decisionsResult.error,
    automationResult.error,
    journalResult.error,
    healthResult.error,
    latestScanResult.error,
  ].filter(Boolean) as string[];

  const latestScan = latestScanResult.data;

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Actions</h1>
        <p className="muted" style={{ marginBottom: 18 }}>
          Items requiring your attention. Configuration, review decisions, and automation controls.
        </p>

        <OperatorActions schedulerRunning={healthResult.data?.scheduler_running ?? false} />

        {errors.length > 0 ? (
          <div style={{ marginBottom: 16 }}>
            {errors.map((err, i) => (
              <p key={i} className="negative small" style={{ margin: '4px 0' }}>
                {err}
              </p>
            ))}
          </div>
        ) : null}

        <ActionList items={items} />
      </section>

      <div className="grid grid-2" style={{ alignItems: 'start', gap: 20 }}>
        <section className="card">
          <h2 style={{ marginBottom: 8 }}>Latest run ranking</h2>
          {latestScanResult.error ? (
            <p className="negative">{latestScanResult.error}</p>
          ) : latestScan?.results?.length ? (
            <RankTable variant="compact" results={latestScan.results} topN={3} />
          ) : (
            <p className="muted">No ranked rows from the latest scan yet.</p>
          )}
        </section>

        <RankBuySimulationPanel latestScan={latestScan} />
      </div>
      <GemmaTestButton />
    </main>
  );
}
