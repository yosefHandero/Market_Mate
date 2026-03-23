import { DecisionRow } from "@/lib/types";

function formatConfidence(value: number) {
  return Number.isFinite(value) ? value.toFixed(1) : "—";
}

export function DecisionPanel({
  rows,
  errorMessage,
}: {
  rows: DecisionRow[];
  errorMessage?: string | null;
}) {
  if (errorMessage) {
    return <p className="negative">{errorMessage}</p>;
  }

  if (!rows.length) {
    return (
      <p className="muted">
        No decisions available yet.
      </p>
    );
  }

  const stockRows = rows.filter((row) => row.asset_type === "stock");
  const cryptoRows = rows.filter((row) => row.asset_type === "crypto");

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <DecisionSection
        title={`Stocks (${stockRows.length})`}
        rows={stockRows}
        emptyMessage="No stock decisions available yet."
      />
      <DecisionSection
        title={`Crypto (${cryptoRows.length})`}
        rows={cryptoRows}
        emptyMessage="No crypto decisions available yet."
      />
    </div>
  );
}

function DecisionSection({
  title,
  rows,
  emptyMessage,
}: {
  title: string;
  rows: DecisionRow[];
  emptyMessage: string;
}) {
  return (
    <section style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0, fontSize: "1rem" }}>{title}</h2>
      </div>
      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Signal</th>
                <th>Confidence</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.asset_type}-${row.symbol}-${row.signal}-${row.last_updated}-${index}`}>
                  <td>
                    <strong>{row.symbol}</strong>
                  </td>
                  <td>{row.signal}</td>
                  <td>{formatConfidence(row.confidence)}</td>
                  <td>
                    <details className="inline-details">
                      <summary>View details</summary>
                      <div className="detail-panel small">
                        <div>
                          <span className="muted">Calibration:</span> {row.calibration_source}
                        </div>
                        <div>
                          <span className="muted">Key metrics:</span> {row.short_metric_summary}
                        </div>
                        <div>
                          <span className="muted">Last updated:</span>{" "}
                          {new Date(row.last_updated).toLocaleString()}
                        </div>
                      </div>
                    </details>
                  </td>
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

