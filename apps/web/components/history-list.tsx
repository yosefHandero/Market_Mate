import type { ScanRun } from '@/lib/types';
import { MarketStatusBadge } from '@/components/market-status-badge';

export function HistoryList({ runs }: { runs: ScanRun[] }) {
  return (
    <div className="history-list">
      {runs.map((run) => (
        <div className="history-item" key={run.run_id}>
          <div className="header-row">
            <div>
              <strong>{new Date(run.created_at).toLocaleString()}</strong>
              <div className="muted small">Top ticker: {run.results[0]?.ticker ?? '—'}</div>
            </div>
            <MarketStatusBadge status={run.market_status} />
          </div>
          <div className="muted small">Scanned {run.scan_count} tickers</div>
          <div className="small" style={{ marginTop: 8 }}>
            {(run.results || [])
              .slice(0, 3)
              .map((r) => `${r.ticker} (${r.score.toFixed(0)})`)
              .join(' • ')}
          </div>
        </div>
      ))}
    </div>
  );
}
