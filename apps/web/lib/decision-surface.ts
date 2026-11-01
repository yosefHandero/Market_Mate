import { SCAN_FRESH_MAX_MINUTES } from '@/lib/freshness';
import type { ScanAssetCoverage } from '@/lib/types';

export const VISIBLE_CANDIDATE_LIMIT = 3;

export function formatScanUpdated(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const timestamp = Date.parse(normalized);
  if (!Number.isFinite(timestamp)) return null;
  return new Date(timestamp).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function ageMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const timestamp = Date.parse(normalized);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, (Date.now() - timestamp) / 60_000);
}

export function isScanStale(
  health: {
    scan_fresh?: boolean | null;
    last_scan_age_minutes?: number | null;
    max_stale_minutes?: number | null;
  } | null,
  latestScan: { created_at?: string | null; scan_fresh?: boolean | null } | null,
): boolean {
  if (health?.scan_fresh === false || latestScan?.scan_fresh === false) return true;
  const storedAge =
    typeof health?.last_scan_age_minutes === 'number' && Number.isFinite(health.last_scan_age_minutes)
      ? health.last_scan_age_minutes
      : null;
  const age = (latestScan?.created_at ? ageMinutes(latestScan.created_at) : null) ?? storedAge;
  if (age == null) return false;
  return age > (health?.max_stale_minutes ?? SCAN_FRESH_MAX_MINUTES);
}

export function isCoverageIncomplete(
  coverage: ScanAssetCoverage[] | null | undefined,
): boolean {
  return (coverage ?? []).some((row) => row.status === 'partial' || row.status === 'unavailable');
}

export type DecisionWarning = {
  message: string;
  tone: 'safety' | 'data';
};

export function buildDecisionWarning(input: {
  killSwitchOn: boolean;
  breakerOpen: boolean;
  scanStale: boolean;
  barsStale?: boolean;
  coverageIncomplete: boolean;
  marketDataDegraded: boolean;
  heldBackCount: number;
}): DecisionWarning | null {
  const safety: string[] = [];
  if (input.killSwitchOn) safety.push('The kill switch is on.');
  if (input.breakerOpen) safety.push('The circuit breaker is open.');

  const stale = input.scanStale || input.barsStale === true;
  const degraded = input.coverageIncomplete || input.marketDataDegraded;
  if (!safety.length && !stale && !degraded && input.heldBackCount <= 0) return null;

  const parts: string[] = [];
  if (safety.length) {
    parts.push(`${safety.join(' ')} Paper actions are blocked.`);
  }
  const heldBack = input.heldBackCount > 0 ? ' Blocked setups stay off this list.' : '';
  if (stale) {
    parts.push(`Stale or incomplete data is affecting these results.${heldBack}`);
  } else if (degraded) {
    parts.push(`Degraded or incomplete data is affecting these results.${heldBack}`);
  } else if (input.heldBackCount > 0) {
    parts.push('Blocked setups stay off this list.');
  }

  return {
    message: parts.join(' '),
    tone: safety.length ? 'safety' : 'data',
  };
}
