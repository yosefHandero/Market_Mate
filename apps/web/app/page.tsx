import { DashboardStatusBanner } from '@/components/dashboard-status-banner';
import { OperatorActions } from '@/components/operator-actions';
import { PersonalAlerts } from '@/components/personal-alerts';
import { TradingWorkspace } from '@/components/trading-workspace';

import {
  getAutomationStatus,
  getLatestDecisions,
  getLatestScan,
  getPaperLedger,
  getPaperLedgerSummary,
  getReadyz,
} from '@/lib/api';
import { buildFrequentWatchTickers } from '@/lib/personal-alerts';
import type { JournalEntry } from '@/lib/types';

type JournalEntriesResult = {
  data: JournalEntry[] | null;
  error: string | null;
};

async function getJournalEntriesForAlerts(): Promise<JournalEntriesResult> {
  const api = (await import('@/lib/api')) as unknown as {
    getJournalEntries?: (limit?: number) => Promise<JournalEntriesResult>;
  };

  if (!Object.prototype.hasOwnProperty.call(api, 'getJournalEntries') || !api.getJournalEntries) {
    return { data: [], error: null };
  }

  return api.getJournalEntries(500);
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) {
    return 'No scan has been recorded yet.';
  }

  return new Date(value).toLocaleString();
}

export default async function HomePage() {
  const [
    decisionsResult,
    automationResult,
    healthResult,
    latestScanResult,
    paperLedgerResult,
    paperLedgerSummaryResult,
    alertJournalEntriesResult,
  ] = await Promise.all([
    getLatestDecisions(),
    getAutomationStatus(),
    getReadyz(),
    getLatestScan(),
    getPaperLedger(100),
    getPaperLedgerSummary(),
    getJournalEntriesForAlerts(),
  ]);

  const errors = [
    decisionsResult.error,
    automationResult.error,
    healthResult.error,
    latestScanResult.error,
  ].filter(Boolean) as string[];
  const paperLedgerError = [paperLedgerResult.error, paperLedgerSummaryResult.error]
    .filter(Boolean)
    .join(' ');
  const alertWatchTickers = buildFrequentWatchTickers(alertJournalEntriesResult.data ?? []);

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 8 }}>Dashboard</h1>
        <p className="muted" style={{ margin: 0 }}>
          Start here to run a scan, review the latest signals, and move into the page you need.
        </p>

        {errors.length ? (
          <div style={{ display: 'grid', gap: 6, marginTop: 16 }}>
            {errors.map((error, index) => (
              <span key={`${error}-${index}`} className="negative small">
                {error}
              </span>
            ))}
          </div>
        ) : null}

        <DashboardStatusBanner
          health={healthResult.data}
          automation={automationResult.data}
          latestScan={latestScanResult.data}
        />

        <div className="detail-panel small" style={{ marginTop: 16 }}>
          <div>
            <span className="muted">Latest scan:</span>{' '}
            {formatTimestamp(latestScanResult.data?.created_at)}
          </div>
          <div>
            <span className="muted">Market status:</span>{' '}
            {latestScanResult.data?.market_status ?? '—'}
          </div>
          <div>
            <span className="muted">Ranked results:</span> {latestScanResult.data?.scan_count ?? 0}
          </div>
          <div>
            <span className="muted">Watchlist size:</span>{' '}
            {latestScanResult.data?.watchlist_size ?? 0}
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <OperatorActions
            schedulerEnabled={healthResult.data?.scheduler_enabled ?? false}
            schedulerRunning={healthResult.data?.scheduler_running ?? false}
            nextScanDueAt={healthResult.data?.next_scan_due_at}
            lastSchedulerRunStartedAt={healthResult.data?.last_scheduler_run_started_at}
            lastSchedulerError={healthResult.data?.last_scheduler_error}
          />
        </div>

        <div style={{ marginTop: 16 }}>
          <PersonalAlerts
            initialLatestScan={latestScanResult.data}
            journalEntries={alertJournalEntriesResult.data ?? []}
            watchTickers={alertWatchTickers}
            journalError={alertJournalEntriesResult.error}
          />
        </div>
      </section>

      <TradingWorkspace
        decisions={decisionsResult.data ?? []}
        decisionsError={decisionsResult.error}
        latestScan={latestScanResult.data}
        initialPaperPositions={paperLedgerResult.data ?? []}
        initialPaperSummary={paperLedgerSummaryResult.data}
        paperLedgerError={paperLedgerError || null}
        automation={automationResult.data}
      />
    </main>
  );
}
