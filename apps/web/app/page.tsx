import { OperatorActions } from '@/components/operator-actions';
import { TradingWorkspace } from '@/components/trading-workspace';

import {
  getAutomationStatus,
  getLatestDecisions,
  getLatestScan,
  getPaperLedger,
  getPaperLedgerSummary,
  getReadyz,
} from '@/lib/api';

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
  ] = await Promise.all([
    getLatestDecisions(),
    getAutomationStatus(),
    getReadyz(),
    getLatestScan(),
    getPaperLedger(100),
    getPaperLedgerSummary(),
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
          <OperatorActions schedulerRunning={healthResult.data?.scheduler_running ?? false} />
        </div>
      </section>

      <TradingWorkspace
        decisions={decisionsResult.data ?? []}
        decisionsError={decisionsResult.error}
        latestScan={latestScanResult.data}
        initialPaperPositions={paperLedgerResult.data ?? []}
        initialPaperSummary={paperLedgerSummaryResult.data}
        paperLedgerError={paperLedgerError || null}
      />
    </main>
  );
}
