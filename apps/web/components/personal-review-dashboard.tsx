import type {
  PersonalReviewAggregate,
  PersonalReviewCohortContext,
  PersonalReviewResult,
} from '@/lib/personal-review';

function safeNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? (Object.is(value, -0) ? 0 : value) : null;
}

function formatCount(value: number | null | undefined) {
  const safeValue = safeNumber(value);
  return safeValue == null ? '0' : String(Math.max(0, Math.round(safeValue)));
}

function formatPct(value: number | null | undefined, signed = false) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return '--';
  const prefix = signed && safeValue > 0 ? '+' : '';
  return `${prefix}${safeValue.toFixed(2)}%`;
}

function formatCurrency(value: number | null | undefined) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return '--';
  return safeValue.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function outcomeTone(value: number | null | undefined) {
  const safeValue = safeNumber(value);
  if (safeValue == null) return undefined;
  if (safeValue > 0) return 'positive';
  if (safeValue < 0) return 'negative';
  return 'muted';
}

function AggregateTable({ title, rows }: { title: string; rows: PersonalReviewAggregate[] }) {
  return (
    <section className="card">
      <h2 style={{ marginBottom: 12 }}>{title}</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Group</th>
              <th>Sample</th>
              <th>Win rate</th>
              <th>Baseline win</th>
              <th>Avg P/L</th>
              <th>Baseline avg</th>
              <th>Total P/L</th>
              <th>Sample flag</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>
                  <strong>{row.label}</strong>
                </td>
                <td>{row.sampleSize}</td>
                <td>{formatPct(row.winRatePct)}</td>
                <td>
                  {formatPct(row.baselineWinRatePct)}
                  <div className="muted small">n={row.baselineSampleSize}</div>
                </td>
                <td className={outcomeTone(row.avgPnlPct)}>
                  {formatPct(row.avgPnlPct, true)}
                  <div className="muted small">{formatCurrency(row.avgPnlUsd)}</div>
                </td>
                <td className={outcomeTone(row.baselineAvgPnlPct)}>
                  {formatPct(row.baselineAvgPnlPct, true)}
                  <div className="muted small">{formatCurrency(row.baselineAvgPnlUsd)}</div>
                </td>
                <td className={outcomeTone(row.totalPnlUsd)}>{formatCurrency(row.totalPnlUsd)}</td>
                <td>{row.lowSample ? <span className="badge amber">Low sample</span> : '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ContextTable({
  validation,
  alignment,
}: {
  validation: PersonalReviewCohortContext | null;
  alignment: PersonalReviewCohortContext[];
}) {
  const rows = [validation, ...alignment].filter(
    (row): row is PersonalReviewCohortContext => row != null,
  );

  return (
    <section className="card">
      <h2 style={{ marginBottom: 8 }}>Validation Context</h2>
      <p className="muted small" style={{ marginBottom: 12 }}>
        Context only. The outcome tables above use closed paper-ledger rows.
      </p>
      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Cohort</th>
                <th>Signals</th>
                <th>Evaluated</th>
                <th>Win rate</th>
                <th>Avg return</th>
                <th>Expectancy</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <td>
                    <strong>{row.label}</strong>
                  </td>
                  <td>{formatCount(row.sampleSize)}</td>
                  <td>{formatCount(row.evaluatedCount)}</td>
                  <td>{formatPct(row.winRatePct)}</td>
                  <td className={outcomeTone(row.avgReturnPct)}>
                    {formatPct(row.avgReturnPct, true)}
                  </td>
                  <td className={outcomeTone(row.expectancyPct)}>
                    {formatPct(row.expectancyPct, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted small">No validation context is available yet.</p>
      )}
    </section>
  );
}

export function PersonalReviewDashboard({
  review,
  errors = [],
}: {
  review: PersonalReviewResult;
  errors?: string[];
}) {
  const baseline = review.baseline;
  const missedWins = review.missedWinsEstimator;

  return (
    <section style={{ display: 'grid', gap: 16 }}>
      {errors.length ? (
        <div className="card">
          <div className="negative small">{errors.join(' | ')}</div>
        </div>
      ) : null}

      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Readiness Outcome Review</h2>
        <p className="muted" style={{ marginBottom: 4 }}>
          Heuristic review. Outcomes are paper-only.
        </p>
        <p className="muted" style={{ marginBottom: 16 }}>
          Low sample sizes can be misleading.
        </p>

        <div className="kpis" style={{ marginTop: 0, marginBottom: 0 }}>
          <div className="kpi">
            <div className="kpi-label">Closed outcome sample</div>
            <div className="kpi-value">{baseline.sampleSize}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Paper win rate</div>
            <div className="kpi-value">{formatPct(baseline.winRatePct)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Avg paper P/L</div>
            <div className={`kpi-value ${outcomeTone(baseline.avgPnlPct) ?? ''}`}>
              {formatPct(baseline.avgPnlPct, true)}
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Missed wins estimate</div>
            <div className="kpi-value">{missedWins.estimatedMissedWins}</div>
          </div>
        </div>

        <div className="detail-panel small" style={{ marginTop: 16 }}>
          <div>
            <span className="muted">Paper ledger rows:</span>{' '}
            {formatCount(review.paperSummary.totalCount)}
          </div>
          <div>
            <span className="muted">Open positions:</span>{' '}
            {formatCount(review.paperSummary.openPositions)}
          </div>
          <div>
            <span className="muted">Closed positions:</span>{' '}
            {formatCount(review.paperSummary.closedPositions)}
          </div>
          <div>
            <span className="muted">Ledger win rate:</span>{' '}
            {formatPct(review.paperSummary.winRatePct)}
          </div>
          <div>
            <span className="muted">Realized P/L:</span>{' '}
            {formatCurrency(review.paperSummary.totalRealizedPnlUsd)}
          </div>
          <div>
            <span className="muted">Gross P/L:</span>{' '}
            {formatCurrency(review.paperSummary.grossPnlUsd)}
          </div>
          <div>
            <span className="muted">Max drawdown:</span>{' '}
            {formatCurrency(review.paperSummary.maxDrawdownUsd)}
          </div>
          <div>
            <span className="muted">Blocked but watched:</span> {review.blockedButWatchedCount}
          </div>
        </div>

        {review.warnings.length ? (
          <div className="small muted" style={{ marginTop: 12, lineHeight: 1.8 }}>
            {review.warnings.join(' | ')}
          </div>
        ) : null}
      </section>

      <AggregateTable title="By Readiness Band" rows={review.aggregateByReadinessBand} />
      <AggregateTable title="By Asset Type" rows={review.aggregateByAssetType} />
      <AggregateTable title="By Provider State" rows={review.aggregateByProviderState} />

      <section className="card">
        <h2 style={{ marginBottom: 12 }}>Missed Wins Estimator</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Watched/skipped sample</th>
                <th>Positive outcomes</th>
                <th>Positive rate</th>
                <th>Avg positive P/L</th>
                <th>Total positive P/L</th>
                <th>Blocked and watched wins</th>
                <th>Sample flag</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{missedWins.sampleSize}</td>
                <td>{missedWins.estimatedMissedWins}</td>
                <td>{formatPct(missedWins.winRatePct)}</td>
                <td className={outcomeTone(missedWins.avgPositivePnlPct)}>
                  {formatPct(missedWins.avgPositivePnlPct, true)}
                </td>
                <td className={outcomeTone(missedWins.totalPositivePnlPct)}>
                  {formatPct(missedWins.totalPositivePnlPct, true)}
                </td>
                <td>{missedWins.blockedButWatchedPositiveCount}</td>
                <td>
                  {missedWins.lowSample ? <span className="badge amber">Low sample</span> : '--'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <ContextTable validation={review.validationContext} alignment={review.alignmentContext} />

      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Assumptions</h2>
        <ul className="muted small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
          {review.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}
