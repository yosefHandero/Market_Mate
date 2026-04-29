'use client';

import {
  AutomationStatusResponse,
  ExecutionAuditSummary,
  ExecutionAlignmentResponse,
  HealthResponse,
  ReconciliationReportResponse,
  ThresholdSweepResponse,
  ValidationBucket,
  ValidationSummary,
} from '@/lib/types';

function formatPct(value: number | null) {
  if (value == null) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatRate(value: number | null) {
  if (value == null) return '—';
  return `${value.toFixed(1)}%`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

type BucketSection = {
  title: string;
  rows: ValidationBucket[];
};

function getMeaningfulBucketSections(summary: ValidationSummary): BucketSection[] {
  const sections: BucketSection[] = [
    { title: 'Signal quality buckets', rows: summary.by_signal_label },
    { title: 'Signal type buckets', rows: summary.by_signal },
    { title: 'Confidence buckets', rows: summary.by_confidence_bucket },
    { title: 'Age buckets', rows: summary.by_age_bucket },
    { title: 'Gate outcome buckets', rows: summary.by_signal_and_gate },
    { title: 'Score band buckets', rows: summary.by_score_band },
    { title: 'Regime buckets', rows: summary.by_market_status },
    { title: 'Data grade buckets', rows: summary.by_data_grade },
    { title: 'News source buckets', rows: summary.by_news_source },
  ];

  return sections.filter((section) => {
    const evaluatedRows = section.rows.filter((row) => row.evaluated_count > 0);
    return evaluatedRows.length > 1;
  });
}

function getDistinctThresholdCandidates(sweep: ThresholdSweepResponse) {
  const seen = new Set<string>();

  return sweep.candidates.filter((candidate) => {
    const signature = [
      candidate.kept_signals,
      candidate.blocked_signals,
      candidate.win_rate,
      candidate.avg_return,
      candidate.expectancy,
      candidate.false_positive_rate,
    ].join('|');

    if (seen.has(signature)) {
      return false;
    }

    seen.add(signature);
    return true;
  });
}

function BucketTable({ title, rows }: { title: string; rows: ValidationBucket[] }) {
  const evaluatedRows = rows.filter((row) => row.evaluated_count > 0);
  const visibleRows = evaluatedRows.slice(0, 6);
  const hiddenCount = Math.max(evaluatedRows.length - visibleRows.length, 0);

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>{title}</span>
        <span className="muted small">
          {evaluatedRows.length
            ? `${evaluatedRows.length} evaluated buckets`
            : 'No evaluated buckets'}
        </span>
      </summary>
      <div className="accordion-body">
        {visibleRows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Bucket</th>
                  <th>Eval</th>
                  <th>Win rate</th>
                  <th>Avg return</th>
                  <th>Expectancy</th>
                  <th>After friction</th>
                  <th>False +</th>
                  <th>Sample</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <strong>{row.key}</strong>
                    </td>
                    <td>{row.evaluated_count}</td>
                    <td>{formatRate(row.win_rate)}</td>
                    <td
                      className={
                        row.avg_return != null && row.avg_return >= 0 ? 'positive' : 'negative'
                      }
                    >
                      {formatPct(row.avg_return)}
                    </td>
                    <td
                      className={
                        row.expectancy != null && row.expectancy >= 0 ? 'positive' : 'negative'
                      }
                    >
                      {formatPct(row.expectancy)}
                    </td>
                    <td
                      className={
                        row.expectancy_after_friction != null && row.expectancy_after_friction >= 0
                          ? 'positive'
                          : 'negative'
                      }
                    >
                      {formatPct(row.expectancy_after_friction)}
                    </td>
                    <td>{formatRate(row.false_positive_rate)}</td>
                    <td>{row.is_underpowered ? 'Underpowered' : 'Ready'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small">No evaluated signals yet.</p>
        )}
        {hiddenCount > 0 ? (
          <p className="muted small" style={{ marginTop: 8 }}>
            Showing first {visibleRows.length} of {evaluatedRows.length} evaluated buckets.
          </p>
        ) : null}
      </div>
    </details>
  );
}

function ThresholdTable({ sweep }: { sweep: ThresholdSweepResponse }) {
  const distinctCandidates = getDistinctThresholdCandidates(sweep);
  const visibleCandidates = distinctCandidates.slice(0, 8);
  const recommendation = sweep.recommendation;

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>Threshold candidates</span>
        <span className="muted small">
          {distinctCandidates.length
            ? `${distinctCandidates.length} distinct candidates`
            : 'No candidates yet'}
        </span>
      </summary>
      <div className="accordion-body">
        <div className="kpis" style={{ marginTop: 0, marginBottom: 16 }}>
          <div className="kpi">
            <div className="kpi-label">Threshold status</div>
            <div className="kpi-value">
              {recommendation.evidence_status === 'ready' ? 'Ready' : 'Provisional'}
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Recommendation source</div>
            <div className="kpi-value">
              {recommendation.source === 'candidate' ? 'Evidence-backed' : 'Configured fallback'}
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Recommended min eval</div>
            <div className="kpi-value">{recommendation.min_evaluated_count}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Recommended min win</div>
            <div className="kpi-value">{recommendation.min_win_rate.toFixed(0)}%</div>
          </div>
        </div>
        <p className="muted small" style={{ marginBottom: 12 }}>
          {recommendation.rationale}
        </p>
        {recommendation.warnings.length ? (
          <div className="negative small" style={{ marginBottom: 16 }}>
            {recommendation.warnings.join(' | ')}
          </div>
        ) : null}
        {visibleCandidates.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Min eval</th>
                  <th>Min win</th>
                  <th>Min avg</th>
                  <th>Score band</th>
                  <th>Kept</th>
                  <th>Expectancy</th>
                  <th>After friction</th>
                  <th>False +</th>
                </tr>
              </thead>
              <tbody>
                {visibleCandidates.map((row, index) => (
                  <tr
                    key={`${row.min_evaluated_count}-${row.min_win_rate}-${row.min_avg_return}-${row.score_band_required}-${index}`}
                  >
                    <td>{row.min_evaluated_count}</td>
                    <td>{row.min_win_rate.toFixed(0)}%</td>
                    <td>{formatPct(row.min_avg_return)}</td>
                    <td>{row.score_band_required ? 'Required' : 'Optional'}</td>
                    <td>{row.kept_signals}</td>
                    <td
                      className={
                        row.expectancy != null && row.expectancy >= 0 ? 'positive' : 'negative'
                      }
                    >
                      {formatPct(row.expectancy)}
                    </td>
                    <td
                      className={
                        row.expectancy_after_friction != null && row.expectancy_after_friction >= 0
                          ? 'positive'
                          : 'negative'
                      }
                    >
                      {formatPct(row.expectancy_after_friction)}
                    </td>
                    <td>{formatRate(row.false_positive_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small">Not enough evaluated signals for threshold comparisons yet.</p>
        )}
        {distinctCandidates.length > 0 && distinctCandidates.length < sweep.candidates.length ? (
          <p className="muted small" style={{ marginTop: 8 }}>
            Showing unique result sets to avoid repeated threshold rows.
          </p>
        ) : null}
      </div>
    </details>
  );
}

function TrustReadinessCard({ readiness }: { readiness: HealthResponse }) {
  return (
    <details className="card accordion-card" open>
      <summary className="accordion-summary">
        <span>Current trust readiness</span>
        <span className="muted small">
          {readiness.trust_evidence_ready
            ? 'Threshold evidence ready'
            : 'Threshold evidence not ready'}
        </span>
      </summary>
      <div className="accordion-body">
        <div className="kpis" style={{ marginTop: 0, marginBottom: 16 }}>
          <div className="kpi">
            <div className="kpi-label">Scanner fresh</div>
            <div className="kpi-value">{readiness.scan_fresh ? 'Yes' : 'No'}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Scheduler</div>
            <div className="kpi-value">{readiness.scheduler_running ? 'Running' : 'Degraded'}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">BUY passed eval</div>
            <div className="kpi-value">{readiness.trust_buy_passed_evaluated_count ?? 0}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">SELL passed eval</div>
            <div className="kpi-value">{readiness.trust_sell_passed_evaluated_count ?? 0}</div>
          </div>
        </div>
        <div className="small muted" style={{ lineHeight: 1.8 }}>
          Latest scan: {formatDateTime(readiness.last_scan_at)}
          <br />
          Scan age: {readiness.last_scan_age_minutes != null ? `${readiness.last_scan_age_minutes.toFixed(2)} min` : '—'}
          <br />
          Trust window: {formatDateTime(readiness.trust_window_start)} to {formatDateTime(readiness.trust_window_end)}
          <br />
          Threshold status: {readiness.trust_threshold_evidence_status ?? '—'}
          {' • '}
          Source: {readiness.trust_threshold_source ?? '—'}
          {' • '}
          Warning count: {readiness.trust_threshold_warning_count ?? 0}
          <br />
          Pending due: 15m={readiness.pending_due_15m_count ?? 0} / 1h={readiness.pending_due_1h_count ?? 0} / 1d={readiness.pending_due_1d_count ?? 0}
        </div>
        {readiness.last_scheduler_error ? (
          <div className="negative small" style={{ marginTop: 12 }}>
            Scheduler error: {readiness.last_scheduler_error}
          </div>
        ) : null}
      </div>
    </details>
  );
}

function AutomationLoopCard({ automation }: { automation: AutomationStatusResponse }) {
  const recentIntents = automation.recent_intents.slice(0, 8);
  const budget = automation.budget;
  const breaker = automation.breaker;

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>Automated fake-money loop</span>
        <span className="muted small">
          {automation.enabled ? `${automation.phase} phase` : 'Disabled'}
        </span>
      </summary>
      <div className="accordion-body">
        <div className="kpis" style={{ marginTop: 0, marginBottom: 16 }}>
          <div className="kpi">
            <div className="kpi-label">Requests made</div>
            <div className="kpi-value">{automation.requests_made}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Requests avoided</div>
            <div className="kpi-value">{automation.requests_avoided}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Dedupe hits</div>
            <div className="kpi-value">{automation.dedupe_hits}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Retries</div>
            <div className="kpi-value">{automation.retries}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Hourly budget</div>
            <div className="kpi-value">
              {budget.hourly_used} / {budget.hourly_limit}
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Breaker</div>
            <div className="kpi-value">{breaker.state}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Candidates</div>
            <div className="kpi-value">{automation.candidates_considered}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Reached execution</div>
            <div className="kpi-value">{automation.candidates_reached_execution_call}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Filter rate</div>
            <div className="kpi-value">
              {automation.filter_rate_pct != null ? `${automation.filter_rate_pct}%` : '—'}
            </div>
          </div>
        </div>
        <div className="small muted" style={{ lineHeight: 1.8 }}>
          Dry run only: {automation.dry_run_only ? 'Yes' : 'No'}
          <br />
          Kill switch: {automation.kill_switch_enabled ? 'Enabled' : 'Off'}
          <br />
          Last processed run: {automation.last_processed_run_id ?? '—'}
          {' • '}
          {formatDateTime(automation.last_processed_run_at)}
          <br />
          Last recovery: {formatDateTime(automation.last_recovery_at)}
          <br />
          Budget pressure: daily {budget.daily_used}/{budget.daily_limit}
          {' • '}
          symbol window {budget.per_symbol_window_limit} per{' '}
          {(budget.per_symbol_window_seconds / 3600).toFixed(0)}h
          <br />
          Blocked: budget={automation.blocked_by_budget} gate={automation.blocked_by_gate} cooldown=
          {automation.blocked_by_cooldown} circuit={automation.blocked_by_circuit}
          <br />
          Breaker probe: owner={breaker.probe_owner ?? '—'} • expires{' '}
          {formatDateTime(breaker.probe_expires_at)}
        </div>
        {breaker.last_error ? (
          <div className="negative small" style={{ marginTop: 12 }}>
            Breaker error: {breaker.last_error}
          </div>
        ) : null}
        {recentIntents.length ? (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Status</th>
                  <th>Req used</th>
                  <th>Next retry</th>
                </tr>
              </thead>
              <tbody>
                {recentIntents.map((intent) => (
                  <tr key={intent.id}>
                    <td>{formatDateTime(intent.created_at)}</td>
                    <td>
                      <strong>{intent.symbol}</strong>
                    </td>
                    <td>{intent.side}</td>
                    <td>{intent.status}</td>
                    <td>{intent.request_count_used}</td>
                    <td>{formatDateTime(intent.next_retry_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small" style={{ marginTop: 12 }}>
            No automation intents have been recorded yet.
          </p>
        )}
      </div>
    </details>
  );
}

function AuditTable({ audits }: { audits: ExecutionAuditSummary[] }) {
  const visibleAudits = audits.slice(0, 12);

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>Execution audits</span>
        <span className="muted small">
          {audits.length ? `${audits.length} recent rows` : 'No audits yet'}
        </span>
      </summary>
      <div className="accordion-body">
        {visibleAudits.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Ticker</th>
                  <th>Status</th>
                  <th>Signal</th>
                  <th>Gate</th>
                  <th>Trust basis</th>
                  <th>Broker</th>
                </tr>
              </thead>
              <tbody>
                {visibleAudits.map((audit) => (
                  <tr key={audit.id}>
                    <td>{formatDateTime(audit.created_at)}</td>
                    <td>
                      <strong>{audit.ticker}</strong>
                    </td>
                    <td>{audit.lifecycle_status}</td>
                    <td>{audit.latest_signal ?? '—'}</td>
                    <td className={audit.trade_gate_allowed ? 'positive' : 'negative'}>
                      {audit.trade_gate_allowed == null
                        ? '—'
                        : audit.trade_gate_allowed
                          ? 'Allowed'
                          : 'Blocked'}
                    </td>
                    <td>
                      <div className="small">
                        {audit.gate_evaluation_mode ?? audit.evidence_basis ?? '—'}
                        <br />
                        {audit.latest_scan_fresh == null
                          ? 'Freshness unknown'
                          : audit.latest_scan_fresh
                            ? 'Fresh scan'
                            : 'Stale scan'}
                      </div>
                    </td>
                    <td>
                      <div className="small">
                        {audit.broker_status ?? '—'}
                        <br />
                        {audit.submitted ? 'Submitted' : 'Not submitted'}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small">No execution audit rows are available yet.</p>
        )}
        {visibleAudits.some((audit) => audit.trade_gate_reason) ? (
          <div className="small muted" style={{ marginTop: 12, lineHeight: 1.8 }}>
            Latest gate reasons:
            <br />
            {visibleAudits
              .filter((audit) => audit.trade_gate_reason)
              .slice(0, 3)
              .map((audit) => `${audit.ticker}: ${audit.trade_gate_reason}`)
              .join(' | ')}
          </div>
        ) : null}
      </div>
    </details>
  );
}

function AlignmentCard({
  title,
  cohort,
}: {
  title: string;
  cohort: ExecutionAlignmentResponse['all_signals'];
}) {
  return (
    <div className="kpi">
      <div className="kpi-label">{title}</div>
      <div className="small muted" style={{ lineHeight: 1.8 }}>
        Signals: {cohort.total_signals}
        <br />
        Evaluated: {cohort.evaluated_count}
        <br />
        Win rate: {formatRate(cohort.win_rate)}
        <br />
        Avg return: {formatPct(cohort.avg_return)}
        <br />
        Expectancy: {formatPct(cohort.expectancy)}
        <br />
        After friction: {formatPct(cohort.expectancy_after_friction)}
        <br />
        False +: {formatRate(cohort.false_positive_rate)}
      </div>
    </div>
  );
}

function ReconciliationCard({ reconciliation }: { reconciliation: ReconciliationReportResponse }) {
  const issues = reconciliation.issues;

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>Paper-loop reconciliation</span>
        <span className={`small ${reconciliation.ok ? 'muted' : 'negative'}`}>
          {reconciliation.ok ? 'ok' : `${reconciliation.total_issues} issue${reconciliation.total_issues !== 1 ? 's' : ''}`}
        </span>
      </summary>
      <div className="accordion-body">
        <div className="small muted" style={{ marginBottom: 12 }}>
          Generated: {formatDateTime(reconciliation.generated_at)}
        </div>
        {issues.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Detail</th>
                  <th>Intent</th>
                  <th>Audit</th>
                  <th>Position</th>
                </tr>
              </thead>
              <tbody>
                {issues.map((issue, index) => (
                  <tr key={index}>
                    <td><strong>{issue.kind}</strong></td>
                    <td>{issue.detail}</td>
                    <td>{issue.intent_id ?? '—'}</td>
                    <td>{issue.execution_audit_id ?? '—'}</td>
                    <td>{issue.paper_position_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small">No ledger-vs-intent mismatches detected.</p>
        )}
      </div>
    </details>
  );
}

function ReconciliationWarningCard({ message }: { message: string }) {
  return (
    <div className="card">
      <div
        style={{
          alignItems: 'center',
          display: 'flex',
          fontWeight: 'bold',
          gap: 16,
          justifyContent: 'space-between',
        }}
      >
        <span>Paper-loop reconciliation</span>
        <span className="small negative">unavailable</span>
      </div>
      <p className="negative small" style={{ marginTop: 8 }}>
        {message}
      </p>
    </div>
  );
}

export function ValidationDashboard({
  summary,
  sweep,
  alignment,
  readiness,
  audits,
  automation,
  reconciliation,
  reconciliationWarning,
  errors,
}: {
  summary: ValidationSummary | null;
  sweep: ThresholdSweepResponse | null;
  alignment: ExecutionAlignmentResponse | null;
  readiness: HealthResponse | null;
  audits: ExecutionAuditSummary[] | null;
  automation: AutomationStatusResponse | null;
  reconciliation?: ReconciliationReportResponse | null;
  reconciliationWarning?: string | null;
  errors?: string[];
}) {
  if (
    !summary &&
    !sweep &&
    !alignment &&
    !readiness &&
    !audits &&
    !automation &&
    !reconciliation &&
    !reconciliationWarning
  ) {
    return (
      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Edge validation</h2>
        {errors?.length ? (
          <div className="negative small" style={{ marginBottom: 8 }}>
            {errors.join(' | ')}
          </div>
        ) : null}
        <p className="muted">Validation metrics are not available yet.</p>
      </section>
    );
  }

  const bucketSections = summary ? getMeaningfulBucketSections(summary) : [];

  return (
    <section style={{ display: 'grid', gap: 16 }}>
      {errors?.length ? (
        <div className="card">
          <div className="negative small">{errors.join(' | ')}</div>
        </div>
      ) : null}

      {readiness && <TrustReadinessCard readiness={readiness} />}

      {automation && <AutomationLoopCard automation={automation} />}

      {reconciliation ? (
        <ReconciliationCard reconciliation={reconciliation} />
      ) : reconciliationWarning ? (
        <ReconciliationWarningCard message={reconciliationWarning} />
      ) : null}

      {summary && (
        <details className="card accordion-card">
          <summary className="accordion-summary">
            <span>Edge validation</span>
            <span className="muted small">
              {summary.evaluated_count} evaluated • {formatRate(summary.overall.win_rate)} win rate
            </span>
          </summary>
          <div className="accordion-body">
            <p className="muted" style={{ marginBottom: 16 }}>
              Primary horizon: <strong>{summary.primary_horizon}</strong>
              {' • '}
              Win threshold: <strong>{formatPct(summary.win_threshold_pct)}</strong>
              {' • '}
              False positive cutoff:{' '}
              <strong>{formatPct(summary.false_positive_threshold_pct)}</strong>
            </p>

            <div className="kpis" style={{ marginTop: 0, marginBottom: 0 }}>
              <div className="kpi">
                <div className="kpi-label">Evaluated signals</div>
                <div className="kpi-value">{summary.evaluated_count}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Win rate</div>
                <div className="kpi-value">{formatRate(summary.overall.win_rate)}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Avg return</div>
                <div className="kpi-value">{formatPct(summary.overall.avg_return)}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">Expectancy</div>
                <div className="kpi-value">{formatPct(summary.overall.expectancy)}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">After friction</div>
                <div className="kpi-value">{formatPct(summary.overall.expectancy_after_friction)}</div>
              </div>
              <div className="kpi">
                <div className="kpi-label">False positive rate</div>
                <div className="kpi-value">{formatRate(summary.overall.false_positive_rate)}</div>
              </div>
            </div>
            {summary.in_sample || summary.out_of_sample ? (
              <p className="muted small" style={{ marginTop: 12 }}>
                In-sample expectancy:{' '}
                {formatPct(summary.in_sample?.expectancy_after_friction ?? summary.in_sample?.expectancy ?? null)}
                {' • '}
                Out-of-sample expectancy:{' '}
                {formatPct(
                  summary.out_of_sample?.expectancy_after_friction ??
                    summary.out_of_sample?.expectancy ??
                    null,
                )}
              </p>
            ) : null}
            {summary.degradation_warnings.length ? (
              <div className="negative small" style={{ marginTop: 8 }}>
                {summary.degradation_warnings.join(' | ')}
              </div>
            ) : null}
            {summary.regime_advisories.length ? (
              <div className="muted small" style={{ marginTop: 8 }}>
                {summary.regime_advisories.join(' | ')}
              </div>
            ) : null}
          </div>
        </details>
      )}

      {summary && (
        <>
          {bucketSections.map((section) => (
            <BucketTable key={section.title} title={section.title} rows={section.rows} />
          ))}
        </>
      )}

      {sweep && <ThresholdTable sweep={sweep} />}

      {alignment && (
        <details className="card accordion-card">
          <summary className="accordion-summary">
            <span>Scanner vs execution</span>
            <span className="muted small">{alignment.all_signals.total_signals} total signals</span>
          </summary>
          <div className="accordion-body">
            <div className="kpis" style={{ marginTop: 0, marginBottom: 0 }}>
              <AlignmentCard title="All signals" cohort={alignment.all_signals} />
              <AlignmentCard title="Submitted paper orders" cohort={alignment.taken_trades} />
              {alignment.automation_dry_run ? (
                <AlignmentCard title="Automation dry-run" cohort={alignment.automation_dry_run} />
              ) : null}
              {alignment.journal_took ? (
                <AlignmentCard title="Journal said took" cohort={alignment.journal_took} />
              ) : null}
              <AlignmentCard title="Skipped / watched" cohort={alignment.skipped_or_watched} />
              <AlignmentCard title="Blocked previews" cohort={alignment.blocked_previews} />
            </div>
          </div>
        </details>
      )}

      {audits ? <AuditTable audits={audits} /> : null}
    </section>
  );
}
