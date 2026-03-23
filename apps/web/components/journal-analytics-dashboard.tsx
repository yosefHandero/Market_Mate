import { JournalAnalytics, JournalAnalyticsBucket } from "@/lib/types";

function formatPct(value: number | null) {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function BucketTable({
  title,
  rows,
}: {
  title: string;
  rows: JournalAnalyticsBucket[];
}) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3 style={{ marginBottom: 12 }}>{title}</h3>

      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Group</th>
                <th>Total</th>
                <th>Open</th>
                <th>Closed</th>
                <th>Win rate</th>
                <th>Avg P/L</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>
                  <td>
                    <strong>{row.key}</strong>
                  </td>
                  <td>{row.total}</td>
                  <td>{row.open_count}</td>
                  <td>{row.closed_count}</td>
                  <td>
                    {row.win_rate != null ? `${row.win_rate.toFixed(0)}%` : "—"}
                  </td>
                  <td
                    className={
                      row.avg_pnl_pct != null
                        ? row.avg_pnl_pct >= 0
                          ? "positive"
                          : "negative"
                        : ""
                    }
                  >
                    {formatPct(row.avg_pnl_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted small">No data yet.</p>
      )}
    </div>
  );
}

export function JournalAnalyticsDashboard({
  analytics,
}: {
  analytics: JournalAnalytics;
}) {
  return (
    <div>
      <div className="card">
        <h2>Journal analytics</h2>

        <div className="kpis" style={{ marginTop: 12, marginBottom: 0 }}>
          <div className="kpi">
            <div className="kpi-label">Total entries</div>
            <div className="kpi-value">{analytics.total_entries}</div>
          </div>

          <div className="kpi">
            <div className="kpi-label">Open trades</div>
            <div className="kpi-value">{analytics.open_trades}</div>
          </div>

          <div className="kpi">
            <div className="kpi-label">Closed trades</div>
            <div className="kpi-value">{analytics.closed_trades}</div>
          </div>

          <div className="kpi">
            <div className="kpi-label">Win rate</div>
            <div className="kpi-value">
              {analytics.win_rate != null
                ? `${analytics.win_rate.toFixed(0)}%`
                : "—"}
            </div>
          </div>
        </div>

        <div className="small muted" style={{ marginTop: 12, lineHeight: 1.8 }}>
          Took: {analytics.took_count}
          {" • "}
          Skipped: {analytics.skipped_count}
          {" • "}
          Watching: {analytics.watching_count}
          {" • "}
          Avg P/L: {formatPct(analytics.avg_pnl_pct)}
        </div>
      </div>

      <BucketTable
        title="Performance by signal strength"
        rows={analytics.by_signal_label}
      />

      <BucketTable
        title="Performance by news source"
        rows={analytics.by_news_source}
      />

      <BucketTable title="Performance by ticker" rows={analytics.by_ticker} />
    </div>
  );
}
