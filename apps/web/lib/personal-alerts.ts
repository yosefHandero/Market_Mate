import { computeTradeReadiness } from '@/lib/readiness';
import type { JournalEntry, ScanResult, ScanRun } from '@/lib/types';

const FREQUENT_WATCHER_WINDOW_DAYS = 14;

export type PersonalAlertMatch = {
  id: string;
  runId: string;
  ticker: string;
  readinessScore: number;
  row: ScanResult;
};

function normalizeTicker(value: string): string {
  return value.trim().toUpperCase();
}

function timestampMs(value: string | null | undefined): number {
  const timestamp = value ? new Date(value).getTime() : Number.NaN;
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY;
}

function toSet(values: Iterable<string>): Set<string> {
  return new Set(
    Array.from(values)
      .map(normalizeTicker)
      .filter(Boolean),
  );
}

export function personalAlertId(runId: string, ticker: string): string {
  return `${runId}:${normalizeTicker(ticker)}`;
}

export function buildFrequentWatchTickers(
  entries: JournalEntry[],
  now: Date = new Date(),
): string[] {
  const cutoff = now.getTime() - FREQUENT_WATCHER_WINDOW_DAYS * 24 * 60 * 60 * 1000;
  const byTicker = new Map<string, { ticker: string; count: number; lastSeenAt: string }>();

  for (const entry of entries) {
    const ticker = normalizeTicker(entry.ticker);
    const entryTimestamp = timestampMs(entry.created_at);

    if (!ticker || entryTimestamp < cutoff || !['watching', 'took'].includes(entry.decision)) {
      continue;
    }

    const existing = byTicker.get(ticker);
    if (!existing) {
      byTicker.set(ticker, { ticker, count: 1, lastSeenAt: entry.created_at });
      continue;
    }

    existing.count += 1;
    if (entryTimestamp >= timestampMs(existing.lastSeenAt)) {
      existing.lastSeenAt = entry.created_at;
    }
  }

  return Array.from(byTicker.values())
    .sort((left, right) => {
      if (right.count !== left.count) return right.count - left.count;
      return timestampMs(right.lastSeenAt) - timestampMs(left.lastSeenAt);
    })
    .map((watcher) => watcher.ticker);
}

export function shouldNotify(
  latestScan: ScanRun | null,
  prevSeenIds: Iterable<string>,
  threshold: number,
  watchTickers: Iterable<string>,
): PersonalAlertMatch[] {
  if (!latestScan?.run_id || !latestScan.results?.length) {
    return [];
  }

  const seenIds = new Set(prevSeenIds);
  const watched = toSet(watchTickers);
  if (!watched.size) {
    return [];
  }

  const minimumReadiness = Number.isFinite(threshold) ? threshold : 70;
  const matches = new Map<string, PersonalAlertMatch>();

  for (const row of latestScan.results) {
    const ticker = normalizeTicker(row.ticker);
    if (!ticker || !watched.has(ticker)) {
      continue;
    }

    const id = personalAlertId(latestScan.run_id, ticker);
    if (seenIds.has(id) || matches.has(id)) {
      continue;
    }

    const readiness = computeTradeReadiness(row);
    if (readiness.score < minimumReadiness) {
      continue;
    }

    matches.set(id, {
      id,
      runId: latestScan.run_id,
      ticker,
      readinessScore: readiness.score,
      row,
    });
  }

  return Array.from(matches.values());
}
