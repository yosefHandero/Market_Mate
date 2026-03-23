"use client";

import {
  ExecutionAlignmentResponse,
  ThresholdSweepResponse,
  ValidationBucket,
  ValidationSummary,
} from "@/lib/types";

function formatPct(value: number | null) {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatRate(value: number | null) {
  if (value == null) return "—";
  return `${value.toFixed(1)}%`;
}

type BucketSection = {
  title: string;
  rows: ValidationBucket[];
};

function getMeaningfulBucketSections(summary: ValidationSummary): BucketSection[] {
  const sections: BucketSection[] = [
    { title: "Signal quality buckets", rows: summary.by_signal_label },
    { title: "Signal type buckets", rows: summary.by_signal },
    { title: "Score band buckets", rows: summary.by_score_band },
    { title: "Regime buckets", rows: summary.by_market_status },
    { title: "News source buckets", rows: summary.by_news_source },
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
    ].join("|");

    if (seen.has(signature)) {
      return false;
    }

    seen.add(signature);
    return true;
  });
}

function BucketTable({
  title,
  rows,
}: {
  title: string;
  rows: ValidationBucket[];
}) {
  const evaluatedRows = rows.filter((row) => row.evaluated_count > 0);
  const visibleRows = evaluatedRows.slice(0, 6);
  const hiddenCount = Math.max(evaluatedRows.length - visibleRows.length, 0);

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>{title}</span>
        <span className="muted small">
          {evaluatedRows.length ? `${evaluatedRows.length} evaluated buckets` : "No evaluated buckets"}
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
                  <th>False +</th>
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
                    <td className={row.avg_return != null && row.avg_return >= 0 ? "positive" : "negative"}>
                      {formatPct(row.avg_return)}
                    </td>
                    <td className={row.expectancy != null && row.expectancy >= 0 ? "positive" : "negative"}>
                      {formatPct(row.expectancy)}
                    </td>
                    <td>{formatRate(row.false_positive_rate)}</td>
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

  return (
    <details className="card accordion-card">
      <summary className="accordion-summary">
        <span>Threshold candidates</span>
        <span className="muted small">
          {distinctCandidates.length
            ? `${distinctCandidates.length} distinct candidates`
            : "No candidates yet"}
        </span>
      </summary>
      <div className="accordion-body">
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
                  <th>False +</th>
                </tr>
              </thead>
              <tbody>
                {visibleCandidates.map((row, index) => (
                  <tr key={`${row.min_evaluated_count}-${row.min_win_rate}-${row.min_avg_return}-${row.score_band_required}-${index}`}>
                    <td>{row.min_evaluated_count}</td>
                    <td>{row.min_win_rate.toFixed(0)}%</td>
                    <td>{formatPct(row.min_avg_return)}</td>
                    <td>{row.score_band_required ? "Required" : "Optional"}</td>
                    <td>{row.kept_signals}</td>
                    <td className={row.expectancy != null && row.expectancy >= 0 ? "positive" : "negative"}>
                      {formatPct(row.expectancy)}
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

function AlignmentCard({
  title,
  cohort,
}: {
  title: string;
  cohort: ExecutionAlignmentResponse["all_signals"];
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
        False +: {formatRate(cohort.false_positive_rate)}
      </div>
    </div>
  );
}

export function ValidationDashboard({
  summary,
  sweep,
  alignment,
  errors,
}: {
  summary: ValidationSummary | null;
  sweep: ThresholdSweepResponse | null;
  alignment: ExecutionAlignmentResponse | null;
  errors?: string[];
}) {
  if (!summary && !sweep && !alignment) {
    return (
      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Edge validation</h2>
        {errors?.length ? (
          <div className="negative small" style={{ marginBottom: 8 }}>
            {errors.join(" | ")}
          </div>
        ) : null}
        <p className="muted">Validation metrics are not available yet.</p>
      </section>
    );
  }

  const bucketSections = summary ? getMeaningfulBucketSections(summary) : [];

  return (
    <section style={{ display: "grid", gap: 16 }}>
      {errors?.length ? (
        <div className="card">
          <div className="negative small">{errors.join(" | ")}</div>
        </div>
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
              {" • "}
              Win threshold: <strong>{formatPct(summary.win_threshold_pct)}</strong>
              {" • "}
              False positive cutoff: <strong>{formatPct(summary.false_positive_threshold_pct)}</strong>
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
                <div className="kpi-label">False positive rate</div>
                <div className="kpi-value">{formatRate(summary.overall.false_positive_rate)}</div>
              </div>
            </div>
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
            <span className="muted small">
              {alignment.all_signals.total_signals} total signals
            </span>
          </summary>
          <div className="accordion-body">
            <div className="kpis" style={{ marginTop: 0, marginBottom: 0 }}>
              <AlignmentCard title="All signals" cohort={alignment.all_signals} />
              <AlignmentCard title="Taken trades" cohort={alignment.taken_trades} />
              <AlignmentCard title="Skipped / watched" cohort={alignment.skipped_or_watched} />
              <AlignmentCard title="Blocked previews" cohort={alignment.blocked_previews} />
            </div>
          </div>
        </details>
      )}
    </section>
  );
}
