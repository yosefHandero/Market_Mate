import type { ScanResult } from '@/lib/types';

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toFixed(digits);
}

export function ConfidenceProvenancePanel({ results }: { results: ScanResult[] }) {
  const storedRows = results.filter((row) => row.layer_details?.confidence?.blend);
  const buyRows = storedRows.filter((row) => row.decision_signal === 'BUY');
  const hasBuyRows = results.some((row) => row.decision_signal === 'BUY');
  const rows = buyRows.length ? buyRows : storedRows;

  return (
    <section className="card proof-placeholder-card" aria-label="Confidence inputs">
      <h2 className="proof-section-title">Confidence inputs</h2>
      <p className="muted small">
        Stored scan-time blend. Decision shows only the capped score.
      </p>
      {rows.length === 0 ? (
        <p className="muted" data-testid="confidence-provenance-empty">
          {results.length ? 'This scan lacks stored confidence blend metadata.' : 'No saved scan results are available.'}
        </p>
      ) : (
        <>
        {!buyRows.length ? (
          <p className="muted small" data-testid="confidence-provenance-no-buys">
            {hasBuyRows
              ? 'Stored confidence inputs are available for other rows; BUY rows lack stored blend metadata.'
              : 'Stored confidence inputs are available; this scan has no BUY rows.'}
          </p>
        ) : null}
        <ul className="decision-reason-list" data-testid="confidence-provenance-list">
          {rows.map((row) => {
            const blend = row.layer_details?.confidence?.blend;
            return (
              <li key={`${row.asset_type}:${row.ticker}`}>
                {row.ticker} ({row.decision_signal}): {blend?.source ?? 'raw'} on {blend?.horizon ?? '--'}, band{' '}
                {blend?.score_band ?? '--'}, samples {blend?.sample_count ?? '--'}, base{' '}
                {formatNumber(blend?.base_score)}
              </li>
            );
          })}
        </ul>
        </>
      )}
    </section>
  );
}
