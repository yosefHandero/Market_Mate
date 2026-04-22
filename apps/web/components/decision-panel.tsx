import type { DecisionSimulationResult, SimulatedDecisionRow } from '@/lib/decision-simulation';
import { DecisionRow } from '@/lib/types';

function formatConfidence(value: number) {
  return Number.isFinite(value) ? value.toFixed(1) : '—';
}

function formatEvidenceScore(value: number | null) {
  return value == null || Number.isNaN(value) ? '—' : value.toFixed(2);
}

function formatCurrency(value: number | null) {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatQuantity(value: number | null) {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

function formatMinutes(value: number | null) {
  if (value == null || Number.isNaN(value)) return '—';
  return `${value.toFixed(1)}m`;
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function simulationBadgeTone(simulationRow: SimulatedDecisionRow) {
  if (simulationRow.simulatedAction === 'buy') return 'green';
  if (simulationRow.simulatedAction === 'sell') return 'blue';
  if (simulationRow.simulatedAction === 'hold') return 'amber';
  return simulationRow.eligibility === 'review' ? 'amber' : 'red';
}

function actionBadgeTone(action: string | null): string | null {
  if (action === 'dry_run') return 'green';
  if (action === 'review') return 'amber';
  if (action === 'blocked') return 'red';
  return null;
}

function ActionBadge({ action }: { action: string | null }) {
  const tone = actionBadgeTone(action);
  const label = action?.replace('_', ' ') ?? '—';
  if (tone) {
    return <span className={`badge ${tone}`}>{label}</span>;
  }
  return <span className="muted">{label}</span>;
}

function degradedFreshnessCount(flags: Record<string, string> | null): number {
  if (!flags) return 0;
  return Object.values(flags).filter((v) => v !== 'ok').length;
}

function simulationSummaryText(simulationRow: SimulatedDecisionRow) {
  if (simulationRow.simulatedAction === 'blocked') {
    return simulationRow.blockedReason ?? 'Blocked.';
  }

  if (simulationRow.simulatedAction === 'hold') {
    return 'No simulated trade.';
  }

  return `${formatCurrency(simulationRow.simulatedOrderValue)} · ${formatQuantity(
    simulationRow.simulatedQuantity,
  )} units`;
}

/** Operational support for action (not predictive confidence). */
export function operationalSupportLabel(row: DecisionRow): 'Eligible' | 'Review' | 'Blocked' | '—' {
  const e = row.execution_eligibility;
  if (row.signal === 'HOLD') return '—';
  if (e === 'eligible') return 'Eligible';
  if (e === 'review') return 'Review';
  if (e === 'not_applicable') return '—';
  return 'Blocked';
}

export function DecisionPanel({
  rows,
  errorMessage,
  variant = 'default',
  simulation,
}: {
  rows: DecisionRow[];
  errorMessage?: string | null;
  variant?: 'default' | 'compact';
  simulation?: DecisionSimulationResult | null;
}) {
  if (errorMessage) {
    return <p className="negative">{errorMessage}</p>;
  }

  if (!rows.length) {
    return <p className="muted">No decisions available yet.</p>;
  }

  const displayRows = rows.map((row, index) => ({
    row,
    simulationRow: simulation?.rows[index] ?? null,
  }));
  const stockRows = displayRows.filter((item) => item.row.asset_type === 'stock');
  const cryptoRows = displayRows.filter((item) => item.row.asset_type === 'crypto');

  if (variant === 'compact') {
    return (
      <div style={{ display: 'grid', gap: 20 }}>
        <DecisionSectionCompact
          title={`Stocks (${stockRows.length})`}
          items={stockRows}
          emptyMessage="No stock decisions available yet."
          showSimulation={Boolean(simulation)}
        />
        <DecisionSectionCompact
          title={`Crypto (${cryptoRows.length})`}
          items={cryptoRows}
          emptyMessage="No crypto decisions available yet."
          showSimulation={Boolean(simulation)}
        />
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      <DecisionSection
        title={`Stocks (${stockRows.length})`}
        items={stockRows}
        emptyMessage="No stock decisions available yet."
        showSimulation={Boolean(simulation)}
      />
      <DecisionSection
        title={`Crypto (${cryptoRows.length})`}
        items={cryptoRows}
        emptyMessage="No crypto decisions available yet."
        showSimulation={Boolean(simulation)}
      />
    </div>
  );
}

function DecisionSectionCompact({
  title,
  items,
  emptyMessage,
  showSimulation,
}: {
  title: string;
  items: Array<{ row: DecisionRow; simulationRow: SimulatedDecisionRow | null }>;
  emptyMessage: string;
  showSimulation: boolean;
}) {
  return (
    <section style={{ display: 'grid', gap: 10 }}>
      <h2 style={{ margin: 0, fontSize: '1rem' }}>{title}</h2>
      {items.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Action</th>
                <th>Operational support</th>
                <th>Recommended action</th>
                <th>Freshness</th>
                {showSimulation ? <th>Simulation</th> : null}
              </tr>
            </thead>
            <tbody>
              {items.map(({ row, simulationRow }, index) => (
                <tr
                  key={`${row.asset_type}-${row.symbol}-${row.signal}-${row.last_updated}-${index}`}
                >
                  <td>
                    <strong>{row.symbol}</strong>
                  </td>
                  <td>{row.signal}</td>
                  <td>{operationalSupportLabel(row)}</td>
                  <td><ActionBadge action={row.recommended_action} /></td>
                  <td className="muted small">
                    Updated {new Date(row.last_updated).toLocaleString()}
                    <br />
                    Bar age {formatMinutes(row.bar_age_minutes)}
                    {degradedFreshnessCount(row.freshness_flags) > 0 ? (
                      <>
                        <br />
                        <span className="negative">
                          {degradedFreshnessCount(row.freshness_flags)} degraded input{degradedFreshnessCount(row.freshness_flags) > 1 ? 's' : ''}
                        </span>
                      </>
                    ) : null}
                  </td>
                  {showSimulation ? (
                    <td>
                      <SimulationCell simulationRow={simulationRow} />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{emptyMessage}</p>
      )}
    </section>
  );
}

function DecisionSection({
  title,
  items,
  emptyMessage,
  showSimulation,
}: {
  title: string;
  items: Array<{ row: DecisionRow; simulationRow: SimulatedDecisionRow | null }>;
  emptyMessage: string;
  showSimulation: boolean;
}) {
  return (
    <section style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0, fontSize: '1rem' }}>{title}</h2>
      </div>
      {items.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Signal</th>
                <th>Calibrated ranking score</th>
                <th>Evidence quality</th>
                <th>Action</th>
                <th>Details</th>
                {showSimulation ? <th>Simulation</th> : null}
              </tr>
            </thead>
            <tbody>
              {items.map(({ row, simulationRow }, index) => (
                <tr
                  key={`${row.asset_type}-${row.symbol}-${row.signal}-${row.last_updated}-${index}`}
                >
                  <td>
                    <strong>{row.symbol}</strong>
                  </td>
                  <td>{row.signal}</td>
                  <td>
                    {formatConfidence(row.confidence)}
                    {row.confidence_label ? (
                      <span className="muted small"> ({row.confidence_label})</span>
                    ) : null}
                  </td>
                  <td>
                    {row.evidence_quality ?? '—'} ({formatEvidenceScore(row.evidence_quality_score)})
                  </td>
                  <td><ActionBadge action={row.recommended_action} /></td>
                  <td>
                    <details className="inline-details">
                      <summary>View details</summary>
                      <div className="detail-panel small">
                        <div>
                          <span className="muted">Raw score:</span>{' '}
                          {row.raw_score != null ? formatConfidence(row.raw_score) : '—'}
                        </div>
                        <div>
                          <span className="muted">Calibration source:</span> {row.calibration_source}
                        </div>
                        <div>
                          <span className="muted">Data grade:</span> {row.data_grade ?? '—'}
                        </div>
                        <div>
                          <span className="muted">Execution eligibility:</span>{' '}
                          {row.execution_eligibility ?? '—'}
                        </div>
                        <div>
                          <span className="muted">Recommended action:</span>{' '}
                          {row.recommended_action ?? '—'}
                        </div>
                        <div>
                          <span className="muted">Provider status:</span> {row.provider_status ?? '—'}
                        </div>
                        <div>
                          <span className="muted">Bar age:</span> {formatMinutes(row.bar_age_minutes)}
                        </div>
                        <div>
                          <span className="muted">Gate passed (scan):</span>{' '}
                          {row.gate_passed == null ? '—' : row.gate_passed ? 'yes' : 'no'}
                        </div>
                        {row.evidence_quality_reasons?.length ? (
                          <div>
                            <span className="muted">Evidence reasons:</span>
                            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                              {row.evidence_quality_reasons.map((reason, i) => (
                                <li key={i}>{reason}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {row.freshness_flags && Object.entries(row.freshness_flags).some(([, v]) => v !== 'ok') ? (
                          <div>
                            <span className="muted">Freshness warnings:</span>{' '}
                            <span className="negative">
                              {Object.entries(row.freshness_flags)
                                .filter(([, v]) => v !== 'ok')
                                .map(([k, v]) => `${k}: ${v}`)
                                .join(' · ')}
                            </span>
                          </div>
                        ) : null}
                        {Object.keys(row.score_contributions ?? {}).length ? (
                          <div>
                            <span className="muted">Score contributions:</span>{' '}
                            {Object.entries(row.score_contributions)
                              .sort((a, b) => b[1] - a[1])
                              .map(([key, value]) => `${key} ${value.toFixed(1)}`)
                              .join(' • ')}
                          </div>
                        ) : null}
                        <div>
                          <span className="muted">Strategy:</span> {row.strategy_version ?? '—'}
                        </div>
                        <div>
                          <span className="muted">Key metrics:</span> {row.short_metric_summary}
                        </div>
                        <div>
                          <span className="muted">Last updated:</span>{' '}
                          {new Date(row.last_updated).toLocaleString()}
                        </div>
                      </div>
                    </details>
                  </td>
                  {showSimulation ? (
                    <td>
                      <SimulationCell simulationRow={simulationRow} />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{emptyMessage}</p>
      )}
    </section>
  );
}

function SimulationCell({ simulationRow }: { simulationRow: SimulatedDecisionRow | null }) {
  if (!simulationRow) {
    return <span className="muted small">Simulation unavailable.</span>;
  }

  return (
    <div style={{ display: 'grid', gap: 8, minWidth: 260 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span className={`badge ${simulationBadgeTone(simulationRow)}`}>
          {titleCase(simulationRow.simulatedAction)}
        </span>
        <span className="muted small">{titleCase(simulationRow.eligibility).replace('_', ' ')}</span>
        <span className="muted small">Price {formatCurrency(simulationRow.price)}</span>
      </div>
      <div className="small">{simulationSummaryText(simulationRow)}</div>
      <details className="inline-details">
        <summary>Simulation details</summary>
        <div className="detail-panel small">
          <div>
            <span className="muted">Simulated action:</span>{' '}
            {titleCase(simulationRow.simulatedAction)}
          </div>
          <div>
            <span className="muted">Simulated order value:</span>{' '}
            {formatCurrency(simulationRow.simulatedOrderValue)}
          </div>
          <div>
            <span className="muted">Simulated quantity:</span>{' '}
            {formatQuantity(simulationRow.simulatedQuantity)}
          </div>
          <div>
            <span className="muted">Blocked reason:</span> {simulationRow.blockedReason ?? '—'}
          </div>
          <div>
            <span className="muted">Post-trade cash:</span>{' '}
            {formatCurrency(simulationRow.postTradeCash)}
          </div>
          <div>
            <span className="muted">Post-trade position:</span>{' '}
            {formatQuantity(simulationRow.postTradePositionQuantity)} units (
            {formatCurrency(simulationRow.postTradePositionMarketValue)})
          </div>
          <div>
            <span className="muted">Estimated portfolio value:</span>{' '}
            {formatCurrency(simulationRow.estimatedPortfolioValue)}
          </div>
        </div>
      </details>
    </div>
  );
}
