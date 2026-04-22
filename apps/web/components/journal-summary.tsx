import { JournalEntry } from '@/lib/types';

export function JournalSummary({ entries }: { entries: JournalEntry[] }) {
  const tookCount = entries.filter((entry) => entry.decision === 'took').length;
  const skippedCount = entries.filter((entry) => entry.decision === 'skipped').length;
  const watchingCount = entries.filter((entry) => entry.decision === 'watching').length;

  const openTradeCount = entries.filter(
    (entry) => entry.decision === 'took' && entry.exit_price == null,
  ).length;

  const closedTradeCount = entries.filter(
    (entry) => entry.decision === 'took' && entry.exit_price != null,
  ).length;

  const tookWithPnl = entries.filter((entry) => entry.decision === 'took' && entry.pnl_pct != null);

  const avgTookPnl = tookWithPnl.length
    ? tookWithPnl.reduce((sum, entry) => sum + (entry.pnl_pct ?? 0), 0) / tookWithPnl.length
    : null;

  const tookWins = tookWithPnl.filter((entry) => (entry.pnl_pct ?? 0) > 0).length;

  const tookWinRate = tookWithPnl.length ? (tookWins / tookWithPnl.length) * 100 : null;

  const tookStrongCount = entries.filter(
    (entry) => entry.decision === 'took' && entry.signal_label === 'strong',
  ).length;

  const tookWatchCount = entries.filter(
    (entry) => entry.decision === 'took' && entry.signal_label === 'watch',
  ).length;

  const tookStrongWithPnl = entries.filter(
    (entry) =>
      entry.decision === 'took' && entry.signal_label === 'strong' && entry.pnl_pct != null,
  );

  const tookWatchWithPnl = entries.filter(
    (entry) => entry.decision === 'took' && entry.signal_label === 'watch' && entry.pnl_pct != null,
  );

  const avgStrongPnl = tookStrongWithPnl.length
    ? tookStrongWithPnl.reduce((sum, entry) => sum + (entry.pnl_pct ?? 0), 0) /
      tookStrongWithPnl.length
    : null;

  const avgWatchPnl = tookWatchWithPnl.length
    ? tookWatchWithPnl.reduce((sum, entry) => sum + (entry.pnl_pct ?? 0), 0) /
      tookWatchWithPnl.length
    : null;

  const tookMarketauxWithPnl = entries.filter(
    (entry) =>
      entry.decision === 'took' && entry.news_source === 'marketaux' && entry.pnl_pct != null,
  );

  const tookCacheWithPnl = entries.filter(
    (entry) => entry.decision === 'took' && entry.news_source === 'cache' && entry.pnl_pct != null,
  );

  const tookSkippedNewsWithPnl = entries.filter(
    (entry) =>
      entry.decision === 'took' && entry.news_source === 'skipped' && entry.pnl_pct != null,
  );

  const avgMarketauxPnl = tookMarketauxWithPnl.length
    ? tookMarketauxWithPnl.reduce((sum, entry) => sum + (entry.pnl_pct ?? 0), 0) /
      tookMarketauxWithPnl.length
    : null;

  const avgCachePnl = tookCacheWithPnl.length
    ? tookCacheWithPnl.reduce((sum, entry) => sum + (entry.pnl_pct ?? 0), 0) /
      tookCacheWithPnl.length
    : null;

  const avgSkippedNewsPnl = tookSkippedNewsWithPnl.length
    ? tookSkippedNewsWithPnl.reduce((sum, entry) => sum + (entry.pnl_pct ?? 0), 0) /
      tookSkippedNewsWithPnl.length
    : null;

  return (
    <div className="history-item" style={{ marginBottom: 10, padding: 12 }}>
      <div className="small muted" style={{ lineHeight: 1.8 }}>
        Total: {entries.length}
        {' • '}
        Took: {tookCount}
        {' • '}
        Skipped: {skippedCount}
        {' • '}
        Watching: {watchingCount}
        {' • '}
        Open trades: {openTradeCount}
        {' • '}
        Closed trades: {closedTradeCount}
      </div>

      <div className="small muted" style={{ lineHeight: 1.8, marginTop: 6 }}>
        Avg took P/L:{' '}
        {avgTookPnl != null ? `${avgTookPnl >= 0 ? '+' : ''}${avgTookPnl.toFixed(2)}%` : '—'}
        {' • '}
        Win rate: {tookWinRate != null ? `${tookWinRate.toFixed(0)}%` : '—'}
        {' • '}
        Strong took: {tookStrongCount}
        {' • '}
        Watch took: {tookWatchCount}
      </div>

      <div className="small muted" style={{ lineHeight: 1.8, marginTop: 6 }}>
        Strong avg:{' '}
        {avgStrongPnl != null ? `${avgStrongPnl >= 0 ? '+' : ''}${avgStrongPnl.toFixed(2)}%` : '—'}
        {' • '}
        Watch avg:{' '}
        {avgWatchPnl != null ? `${avgWatchPnl >= 0 ? '+' : ''}${avgWatchPnl.toFixed(2)}%` : '—'}
      </div>

      <div className="small muted" style={{ lineHeight: 1.8, marginTop: 6 }}>
        Marketaux avg:{' '}
        {avgMarketauxPnl != null
          ? `${avgMarketauxPnl >= 0 ? '+' : ''}${avgMarketauxPnl.toFixed(2)}%`
          : '—'}
        {' • '}
        Cache avg:{' '}
        {avgCachePnl != null ? `${avgCachePnl >= 0 ? '+' : ''}${avgCachePnl.toFixed(2)}%` : '—'}
        {' • '}
        Skipped-news avg:{' '}
        {avgSkippedNewsPnl != null
          ? `${avgSkippedNewsPnl >= 0 ? '+' : ''}${avgSkippedNewsPnl.toFixed(2)}%`
          : '—'}
      </div>
    </div>
  );
}
