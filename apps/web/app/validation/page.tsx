import { ValidationDashboard } from '@/components/validation-dashboard';
import {
  getAutomationStatus,
  getExecutionAlignment,
  getExecutionAudits,
  getReadyz,
  getReconciliationReport,
  getThresholdSweep,
  getValidationSummary,
  RECONCILIATION_UNAVAILABLE_MESSAGE,
} from '@/lib/api';

export default async function ValidationPage() {
  const [
    summaryResult,
    sweepResult,
    alignmentResult,
    readyResult,
    auditsResult,
    automationResult,
    reconciliationResult,
  ] = await Promise.all([
    getValidationSummary(),
    getThresholdSweep(),
    getExecutionAlignment(),
    getReadyz(),
    getExecutionAudits(25),
    getAutomationStatus(),
    getReconciliationReport(),
  ]);

  const errors = [
    summaryResult.error,
    sweepResult.error,
    alignmentResult.error,
    readyResult.error,
    auditsResult.error,
    automationResult.error,
  ].filter(Boolean) as string[];
  const reconciliationWarning = reconciliationResult.error
    ? RECONCILIATION_UNAVAILABLE_MESSAGE
    : null;

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Validation</h1>
        <p className="muted" style={{ marginBottom: 16 }}>
          Outcome analytics, threshold candidates, and execution alignment.
        </p>
        <ValidationDashboard
          summary={summaryResult.data}
          sweep={sweepResult.data}
          alignment={alignmentResult.data}
          readiness={readyResult.data}
          audits={auditsResult.data}
          automation={automationResult.data}
          reconciliation={reconciliationResult.data}
          reconciliationWarning={reconciliationWarning}
          errors={errors}
        />
      </section>
    </main>
  );
}
