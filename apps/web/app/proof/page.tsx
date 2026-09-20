import { ConfidencePerformancePanel } from '@/components/confidence-performance-panel';
import { EvidenceTracksPanel } from '@/components/evidence-tracks-panel';
import { ExecutionAuditList } from '@/components/execution-audit-list';
import { ExitWindowAccuracyPanel } from '@/components/exit-window-accuracy-panel';
import { LiveForwardProgressPanel } from '@/components/live-forward-progress-panel';
import { OperatorActions } from '@/components/operator-actions';
import { PolicyPromotionPanel } from '@/components/policy-promotion-panel';
import { PredictionAccuracyPanel } from '@/components/prediction-accuracy-panel';
import { ProofLedgerSection } from '@/components/proof-ledger-section';
import { ProofSummaryPanel } from '@/components/proof-summary-panel';
import { RiskControlStatus } from '@/components/risk-control-status';
import { WalkForwardProofPanel } from '@/components/walk-forward-proof-panel';
import {
  getAutomationStatus,
  getExecutionAudits,
  getLatestScan,
  getPaperLedger,
  getPaperLedgerSummary,
  getProofSummary,
  getReadyz,
  getSystemReadiness,
} from '@/lib/api';

function buildLatestPriceMap(
  results: { ticker: string; asset_type: string; price: number }[],
): Record<string, number> {
  return Object.fromEntries(
    results.flatMap((row) => [
      [`${row.asset_type.toUpperCase()}:${row.ticker}`, row.price],
      [row.ticker, row.price],
    ]),
  );
}

export default async function ProofPage() {
  const [
    healthResult,
    automationResult,
    systemReadinessResult,
    latestScanResult,
    paperLedgerResult,
    paperLedgerSummaryResult,
    auditsResult,
    proofSummaryResult,
  ] = await Promise.all([
    getReadyz(),
    getAutomationStatus(),
    getSystemReadiness(),
    getLatestScan(),
    getPaperLedger(100),
    getPaperLedgerSummary(),
    getExecutionAudits(50),
    getProofSummary(),
  ]);

  const errors = [
    healthResult.error,
    automationResult.error,
    paperLedgerResult.error,
    paperLedgerSummaryResult.error,
    auditsResult.error,
    proofSummaryResult.error,
  ].filter(Boolean) as string[];

  const workerRunning =
    healthResult.data?.worker_alive ?? healthResult.data?.scheduler_running ?? false;

  const latestPrices = buildLatestPriceMap(latestScanResult.data?.results ?? []);
  const paperLedgerError = [paperLedgerResult.error, paperLedgerSummaryResult.error]
    .filter(Boolean)
    .join(' ');

  return (
    <main className="dashboard-main proof-page">
      <section className="card">
        <h1 className="proof-page-title">Proof</h1>
        <p className="muted small" style={{ marginTop: 0 }}>
          Paper positions, ledger, audits, evidence progress, and operational safety controls.
        </p>
        {errors.length ? (
          <div className="system-health-errors">
            {errors.map((error, index) => (
              <span key={`${error}-${index}`} className="negative small">
                {error}
              </span>
            ))}
          </div>
        ) : null}
      </section>

      <ProofSummaryPanel summary={proofSummaryResult.data} />

      <LiveForwardProgressPanel progress={proofSummaryResult.data?.live_forward} />

      <EvidenceTracksPanel
        evidence={proofSummaryResult.data?.weekly_evidence}
        contract={proofSummaryResult.data?.evidence_contract}
      />

      <PolicyPromotionPanel report={proofSummaryResult.data?.policy_promotion} />

      <RiskControlStatus
        health={healthResult.data}
        automation={automationResult.data}
        systemReadiness={systemReadinessResult.data}
        marketStatus={latestScanResult.data?.market_status ?? null}
      />

      <OperatorActions
        schedulerEnabled={healthResult.data?.scheduler_enabled ?? false}
        schedulerRunning={workerRunning}
        nextScanDueAt={healthResult.data?.next_scan_due_at}
        lastSchedulerRunStartedAt={healthResult.data?.last_scheduler_run_started_at}
        lastSchedulerError={healthResult.data?.last_scheduler_error}
      />

      <ProofLedgerSection
        initialPositions={paperLedgerResult.data ?? []}
        initialSummary={paperLedgerSummaryResult.data}
        initialError={paperLedgerError || null}
        latestPrices={latestPrices}
      />

      <PredictionAccuracyPanel metrics={proofSummaryResult.data?.prediction_accuracy} />

      <ConfidencePerformancePanel performance={proofSummaryResult.data?.confidence_performance} />

      <ExitWindowAccuracyPanel metrics={proofSummaryResult.data?.exit_window_accuracy} />

      <WalkForwardProofPanel summary={proofSummaryResult.data?.walk_forward} />

      <ExecutionAuditList audits={auditsResult.data ?? []} />
    </main>
  );
}
