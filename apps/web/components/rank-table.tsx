import { RankMoreDetailsCell } from '@/components/rank-more-details-cell';
import type { DecisionSignal, ScanResult } from '@/lib/types';

function signalBadge(signal: DecisionSignal) {
  if (signal === 'BUY') return <span className="badge green">BUY</span>;
  if (signal === 'SELL') return <span className="badge red">SELL</span>;
  return <span className="badge">HOLD</span>;
}

type RankTableProps = {
  results: ScanResult[];
  /** `full` (default): core columns + (more details). `compact`: Rank through Day % only. */
  variant?: 'full' | 'compact';
  /** If set, only show this many rows per asset type section. */
  topN?: number;
};

function RankSection({
  title,
  results,
  showExtended,
}: {
  title: string;
  results: ScanResult[];
  showExtended: boolean;
}) {
  if (!results.length) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ marginBottom: 8, fontSize: 14, textTransform: 'uppercase', letterSpacing: '0.08em' }} className="muted">
        {title}
      </h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Ticker</th>
              <th>Signal</th>
              <th>Raw score</th>
              <th>Calibrated score</th>
              <th>Price</th>
              <th>Day %</th>
              {showExtended ? <th>(more details)</th> : null}
            </tr>
          </thead>
          <tbody>
            {results.map((row, index) => (
              <tr key={`${row.ticker}-${row.created_at}`}>
                <td>{index + 1}</td>
                <td>
                  <strong>{row.ticker}</strong>
                </td>
                <td>{signalBadge(row.decision_signal)}</td>
                <td className="score">{row.raw_score.toFixed(1)}</td>
                <td>{row.calibrated_confidence.toFixed(1)}</td>
                <td>${row.price.toFixed(2)}</td>
                <td
                  className={
                    row.price_change_pct > 0
                      ? 'positive'
                      : row.price_change_pct < 0
                        ? 'negative'
                        : 'neutral'
                  }
                >
                  {row.price_change_pct.toFixed(2)}%
                </td>
                {showExtended ? <RankMoreDetailsCell row={row} /> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RankTable({ results, variant = 'full', topN }: RankTableProps) {
  const showExtended = variant !== 'compact';
  let stocks = results.filter((r) => r.asset_type === 'stock');
  let crypto = results.filter((r) => r.asset_type === 'crypto');

  if (topN != null && topN > 0) {
    stocks = stocks.slice(0, topN);
    crypto = crypto.slice(0, topN);
  }

  return (
    <div>
      <RankSection title="Stocks" results={stocks} showExtended={showExtended} />
      <RankSection title="Crypto" results={crypto} showExtended={showExtended} />
    </div>
  );
}
