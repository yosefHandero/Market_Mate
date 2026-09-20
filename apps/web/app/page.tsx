import { DashboardStatusBanner } from '@/components/dashboard-status-banner';
import { DecisionServingPolicyStatus } from '@/components/decision-serving-policy-status';
import { DecisionGrid } from '@/components/decision-grid';
import {
  getAutomationStatus,
  getLatestDecisions,
  getLatestScan,
  getProofSummary,
  getReadyz,
  getSystemReadiness,
} from '@/lib/api';

export default async function DecisionPage() {
  const [
    decisionsResult,
    automationResult,
    healthResult,
    systemReadinessResult,
    latestScanResult,
    proofSummaryResult,
  ] = await Promise.all([
    getLatestDecisions(50),
    getAutomationStatus(),
    getReadyz(),
    getSystemReadiness(),
    getLatestScan(),
    getProofSummary(),
  ]);

  const errors = [
    decisionsResult.error,
    automationResult.error,
    healthResult.error,
    latestScanResult.error,
  ].filter(Boolean) as string[];

  return (
    <main className="dashboard-main decision-page">
      <section className="card system-health-card">
        <div className="system-health-card-head">
          <div>
            <h1 className="system-health-title">Buy Candidates</h1>
            <p className="muted small system-health-subtitle" style={{ margin: 0 }}>
              Top stock and crypto buy candidates ranked by upside probability, with an
              estimated exit window. Paper dry-run only; not financial advice.
            </p>
          </div>
          <DecisionServingPolicyStatus
            report={proofSummaryResult.data?.policy_promotion}
            error={proofSummaryResult.error}
          />
        </div>

        {errors.length ? (
          <div className="system-health-errors">
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
          systemReadiness={systemReadinessResult.data}
        />
      </section>

      <DecisionGrid
        results={latestScanResult.data?.results ?? []}
        topStocks={latestScanResult.data?.top_stocks}
        topCrypto={latestScanResult.data?.top_crypto}
        decisions={decisionsResult.data ?? []}
        automation={automationResult.data}
        decisionsError={decisionsResult.error}
      />
    </main>
  );
}
