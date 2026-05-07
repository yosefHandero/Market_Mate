import { computeTradeReadiness, formatReadiness, type ReadinessBand } from '@/lib/readiness';
import type { AssetType, DecisionSignal, JournalEntry, ScanResult, ScanRun } from '@/lib/types';

const RECENT_WATCHER_WINDOW_DAYS = 14;
const ASSET_TYPE_ORDER: AssetType[] = ['stock', 'crypto'];

type WatchlistRow = {
  ticker: string;
  assetType: AssetType;
  decisionSignal: DecisionSignal;
  readinessBand: ReadinessBand;
  readinessScore: number;
  readinessReason: string;
  lastSeenAt: string;
};

type WatchlistGroup = {
  assetType: AssetType;
  rows: WatchlistRow[];
};

type FrequentWatcher = {
  ticker: string;
  count: number;
  lastDecision: JournalEntry['decision'];
  lastSeenAt: string;
};

function normalizeTicker(value: string): string {
  return value.trim().toUpperCase();
}

function dateMs(value: string | null | undefined): number {
  const ms = value ? new Date(value).getTime() : Number.NaN;
  return Number.isFinite(ms) ? ms : Number.NEGATIVE_INFINITY;
}

function isNewer(left: string, right: string): boolean {
  return dateMs(left) >= dateMs(right);
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Unknown';
  const ms = dateMs(value);
  return Number.isFinite(ms) ? new Date(ms).toLocaleString() : 'Unknown';
}

function formatAssetType(value: AssetType): string {
  if (value === 'stock') return 'Stocks';
  if (value === 'crypto') return 'Crypto';
  return value;
}

function readinessBandLabel(value: ReadinessBand): string {
  if (value === 'high') return 'High';
  if (value === 'watch') return 'Watch';
  if (value === 'low') return 'Low';
  return 'None';
}

function signalBadgeClass(signal: DecisionSignal): string {
  if (signal === 'BUY') return 'badge green';
  if (signal === 'SELL') return 'badge red';
  return 'badge';
}

function readinessBadgeClass(band: ReadinessBand): string {
  if (band === 'high') return 'badge green';
  if (band === 'watch') return 'badge amber';
  if (band === 'low' || band === 'none') return 'badge red';
  return 'badge';
}

function dedupeLatestScanRows(rows: ScanResult[]): ScanResult[] {
  const byTicker = new Map<string, ScanResult>();

  for (const row of rows) {
    const ticker = normalizeTicker(row.ticker);
    if (!ticker) continue;

    const key = `${row.asset_type}:${ticker}`;
    const existing = byTicker.get(key);
    if (!existing || isNewer(row.created_at, existing.created_at)) {
      byTicker.set(key, { ...row, ticker });
    }
  }

  return Array.from(byTicker.values()).sort((a, b) => {
    const assetDiff = ASSET_TYPE_ORDER.indexOf(a.asset_type) - ASSET_TYPE_ORDER.indexOf(b.asset_type);
    if (assetDiff !== 0) return assetDiff;
    return a.ticker.localeCompare(b.ticker);
  });
}

export function buildWatchlistGroups(latestScan: ScanRun | null): WatchlistGroup[] {
  const rows = dedupeLatestScanRows(latestScan?.results ?? []).map((row) => {
    const readiness = computeTradeReadiness(row);

    return {
      ticker: row.ticker,
      assetType: row.asset_type,
      decisionSignal: row.decision_signal,
      readinessBand: readiness.band,
      readinessScore: readiness.score,
      readinessReason: readiness.reason,
      lastSeenAt: row.created_at,
    };
  });

  const groups = new Map<AssetType, WatchlistRow[]>();
  for (const row of rows) {
    groups.set(row.assetType, [...(groups.get(row.assetType) ?? []), row]);
  }

  return ASSET_TYPE_ORDER.flatMap((assetType) => {
    const groupRows = groups.get(assetType) ?? [];
    return groupRows.length ? [{ assetType, rows: groupRows }] : [];
  });
}

export function buildFrequentWatchers(
  entries: JournalEntry[],
  now: Date = new Date(),
): FrequentWatcher[] {
  const cutoffMs = now.getTime() - RECENT_WATCHER_WINDOW_DAYS * 24 * 60 * 60 * 1000;
  const byTicker = new Map<string, FrequentWatcher>();

  for (const entry of entries) {
    const ticker = normalizeTicker(entry.ticker);
    const entryMs = dateMs(entry.created_at);
    if (!ticker || entryMs < cutoffMs || !['watching', 'took'].includes(entry.decision)) {
      continue;
    }

    const existing = byTicker.get(ticker);
    if (!existing) {
      byTicker.set(ticker, {
        ticker,
        count: 1,
        lastDecision: entry.decision,
        lastSeenAt: entry.created_at,
      });
      continue;
    }

    existing.count += 1;
    if (entryMs >= dateMs(existing.lastSeenAt)) {
      existing.lastDecision = entry.decision;
      existing.lastSeenAt = entry.created_at;
    }
  }

  return Array.from(byTicker.values()).sort((a, b) => {
    if (b.count !== a.count) return b.count - a.count;
    return dateMs(b.lastSeenAt) - dateMs(a.lastSeenAt);
  });
}

export function WatchlistView({
  latestScan,
  journalEntries,
  scanError,
  journalError,
  now,
}: {
  latestScan: ScanRun | null;
  journalEntries: JournalEntry[];
  scanError?: string | null;
  journalError?: string | null;
  now?: Date;
}) {
  const groups = buildWatchlistGroups(latestScan);
  const frequentWatchers = buildFrequentWatchers(journalEntries, now);
  const scannedCount = groups.reduce((total, group) => total + group.rows.length, 0);

  return (
    <section style={{ display: 'grid', gap: 20 }}>
      <section className="card">
        <h1 style={{ marginBottom: 6 }}>Watchlist</h1>
        <p className="muted" style={{ margin: 0 }}>
          Read-only view of the latest scanned symbols and recent journal tickers.
        </p>

        <div className="detail-panel small" style={{ marginTop: 16 }}>
          <div>
            <span className="muted">Latest scan:</span> {formatTimestamp(latestScan?.created_at)}
          </div>
          <div>
            <span className="muted">Scanned rows:</span> {scannedCount}
          </div>
          <div>
            <span className="muted">Frequent watchers:</span> {frequentWatchers.length}
          </div>
        </div>

        {scanError ? (
          <p className="negative small" style={{ marginTop: 12, marginBottom: 0 }}>
            {scanError}
          </p>
        ) : null}
        {journalError ? (
          <p className="negative small" style={{ marginTop: 12, marginBottom: 0 }}>
            {journalError}
          </p>
        ) : null}
      </section>

      <section className="card" aria-label="Scanned watchlist">
        <h2 style={{ marginBottom: 8 }}>Scanned Watchlist</h2>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          Derived from the latest scan rows.
        </p>

        {groups.length ? (
          <div style={{ display: 'grid', gap: 18 }}>
            {groups.map((group) => (
              <section key={group.assetType} style={{ display: 'grid', gap: 10 }}>
                <div className="header-row" style={{ marginBottom: 0 }}>
                  <h3 style={{ margin: 0 }}>{formatAssetType(group.assetType)}</h3>
                  <span className="badge">{group.rows.length}</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Last decision_signal</th>
                        <th>Last Readiness band</th>
                        <th>Last seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.rows.map((row) => (
                        <tr key={`${row.assetType}:${row.ticker}`}>
                          <td>
                            <strong>{row.ticker}</strong>
                          </td>
                          <td>
                            <span className={signalBadgeClass(row.decisionSignal)}>
                              {row.decisionSignal}
                            </span>
                          </td>
                          <td>
                            <span className={readinessBadgeClass(row.readinessBand)}>
                              {readinessBandLabel(row.readinessBand)}
                            </span>
                            <div className="muted small" style={{ marginTop: 4 }}>
                              {formatReadiness(row.readinessScore)} | {row.readinessReason}
                            </div>
                          </td>
                          <td className="small">{formatTimestamp(row.lastSeenAt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            No latest scan rows available yet.
          </p>
        )}
      </section>

      <section className="card" aria-label="Frequent watchers">
        <h2 style={{ marginBottom: 8 }}>Frequent Watchers</h2>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          Unique tickers from journal decisions marked watching or took in the last 14 days.
        </p>

        {frequentWatchers.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Recent entries</th>
                  <th>Last journal decision</th>
                  <th>Last touched</th>
                </tr>
              </thead>
              <tbody>
                {frequentWatchers.map((watcher) => (
                  <tr key={watcher.ticker}>
                    <td>
                      <strong>{watcher.ticker}</strong>
                    </td>
                    <td>{watcher.count}</td>
                    <td>
                      <span className={watcher.lastDecision === 'took' ? 'badge green' : 'badge amber'}>
                        {watcher.lastDecision}
                      </span>
                    </td>
                    <td className="small">{formatTimestamp(watcher.lastSeenAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            No recent watching or took journal decisions in the last 14 days.
          </p>
        )}
      </section>
    </section>
  );
}
