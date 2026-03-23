import { ScanResult } from "@/lib/types";

function signalBadgeClass(signalLabel: string) {
  if (signalLabel === "strong") return "green";
  if (signalLabel === "watch") return "blue";
  return "";
}

function newsBadgeClass(newsSource: string) {
  if (newsSource === "marketaux") return "blue";
  if (newsSource === "cache") return "green";
  if (newsSource === "skipped") return "amber";
  return "";
}

export function RankTable({ results }: { results: ScanResult[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Ticker</th>
            <th>Score</th>
            <th>Price</th>
            <th>Day %</th>
            <th>Rel Vol</th>
            <th>Options</th>
            <th>Flags</th>
            <th>Why it is interesting</th>
          </tr>
        </thead>
        <tbody>
          {results.map((row, index) => (
            <tr key={`${row.ticker}-${row.created_at}`}>
              <td>{index + 1}</td>
              <td>
                <strong>{row.ticker}</strong>
              </td>
              <td className="score">{row.score.toFixed(1)}</td>
              <td>${row.price.toFixed(2)}</td>
              <td
                className={
                  row.price_change_pct > 0
                    ? "positive"
                    : row.price_change_pct < 0
                      ? "negative"
                      : "neutral"
                }
              >
                {row.price_change_pct.toFixed(2)}%
              </td>
              <td>{row.relative_volume.toFixed(2)}x</td>
              <td>
                <div className="grid">
                  <span
                    className={`badge ${row.options_flow_bullish ? "green" : "amber"}`}
                  >
                    Flow {row.options_flow_score.toFixed(1)}
                  </span>
                  <span className="badge">
                    P/C {row.options_call_put_ratio.toFixed(2)}
                  </span>
                </div>
              </td>
              <td>
                <div className="grid">
                  <span
                    className={`badge ${signalBadgeClass(row.signal_label)}`}
                  >
                    {row.signal_label.toUpperCase()}
                  </span>
                  <span className={`badge ${newsBadgeClass(row.news_source)}`}>
                    News: {row.news_source}
                  </span>
                  {row.breakout_flag && (
                    <span className="badge blue">Breakout</span>
                  )}
                  {row.filing_flag && (
                    <span className="badge amber">SEC filing</span>
                  )}
                  {row.alert_sent && (
                    <span className="badge green">Telegram</span>
                  )}
                </div>
              </td>
              <td>
                <div style={{ display: "grid", gap: 6 }}>
                  <span>{row.explanation}</span>
                  {row.news_cache_label && (
                    <span className="muted">{row.news_cache_label}</span>
                  )}
                  <span className="muted">{row.options_flow_summary}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
