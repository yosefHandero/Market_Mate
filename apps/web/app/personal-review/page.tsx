import { PersonalReviewDashboard } from '@/components/personal-review-dashboard';
import {
  getExecutionAlignment,
  getExecutionAudits,
  getJournalEntries,
  getPaperLedger,
  getPaperLedgerSummary,
  getValidationSummary,
} from '@/lib/api';
import { buildPersonalReview } from '@/lib/personal-review';

export default async function PersonalReviewPage() {
  const [
    validationResult,
    alignmentResult,
    paperLedgerResult,
    paperLedgerSummaryResult,
    journalEntriesResult,
    auditsResult,
  ] = await Promise.all([
    getValidationSummary(),
    getExecutionAlignment(),
    getPaperLedger(500),
    getPaperLedgerSummary(),
    getJournalEntries(500),
    getExecutionAudits(500),
  ]);

  const errors = [
    validationResult.error,
    alignmentResult.error,
    paperLedgerResult.error,
    paperLedgerSummaryResult.error,
    journalEntriesResult.error,
    auditsResult.error,
  ].filter(Boolean) as string[];

  const review = buildPersonalReview({
    validation: validationResult.data,
    executionAlignment: alignmentResult.data,
    paperLedger: paperLedgerResult.data ?? [],
    paperLedgerSummary: paperLedgerSummaryResult.data,
    journalEntries: journalEntriesResult.data ?? [],
    audits: auditsResult.data ?? [],
  });

  return (
    <main style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Personal Review</h1>
        <p className="muted" style={{ margin: 0 }}>
          A compact paper-trading review of whether Readiness is helping your decisions over time.
        </p>
      </section>

      <PersonalReviewDashboard review={review} errors={errors} />
    </main>
  );
}
