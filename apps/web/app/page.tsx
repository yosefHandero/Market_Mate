import { DecisionGrid } from '@/components/decision-grid';
import { OperatorActions } from '@/components/operator-actions';
import {
  getAutomationStatus,
  getLatestDecisions,
  getLatestScan,
  getReadyz,
} from '@/lib/api';
import { describeUnscoredRequiredInputs, formatScanUpdated, isCoverageIncomplete, isScanStale } from '@/lib/decision-surface';
import { withoutProviderDiagnostics } from '@/lib/scan-provider-data';

export default async function DecisionPage() {
  const [decisionsResult, automationResult, healthResult, latestScanResult] = await Promise.all([
    getLatestDecisions(50),
    getAutomationStatus(),
    getReadyz(),
    getLatestScan(),
  ]);

  const latestScan = latestScanResult.data;
  const updatedLabel = formatScanUpdated(latestScan?.created_at);
  const loadError = [latestScanResult.error, decisionsResult.error].filter(Boolean).join(' ');

  return (
    <main className="dashboard-main decision-page">
      <header className="decision-toolbar">
        <h1 className="decision-title">Buy Candidates</h1>
        <div className="decision-toolbar-side">
          <p className="decision-updated" data-testid="decision-updated">
            {updatedLabel ? `Updated ${updatedLabel}` : 'Not scanned yet'}
          </p>
          <OperatorActions
            mode="scan"
            schedulerEnabled={healthResult.data?.scheduler_enabled ?? false}
            schedulerRunning={healthResult.data?.worker_alive ?? healthResult.data?.scheduler_running ?? false}
            nextScanDueAt={healthResult.data?.next_scan_due_at}
            lastSchedulerRunStartedAt={healthResult.data?.last_scheduler_run_started_at}
            lastSchedulerError={healthResult.data?.last_scheduler_error}
          />
        </div>
      </header>

      {loadError ? (
        <p className="negative decision-load-error" role="alert" data-testid="decision-load-error">
          {loadError}
        </p>
      ) : null}

      <DecisionGrid
        results={withoutProviderDiagnostics(latestScan?.results ?? [])}
        topStocks={withoutProviderDiagnostics(latestScan?.top_stocks ?? [])}
        topCrypto={withoutProviderDiagnostics(latestScan?.top_crypto ?? [])}
        decisions={decisionsResult.data ?? []}
        automation={automationResult.data}
        scanStale={isScanStale(healthResult.data, latestScan)}
        coverageIncomplete={isCoverageIncomplete(latestScan?.coverage)}
        unscoredRequiredInputs={describeUnscoredRequiredInputs(latestScan?.coverage)}
        hasSavedScan={latestScan != null}
      />
    </main>
  );
}
