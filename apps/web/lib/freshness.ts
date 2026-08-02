/**
 * Per-bar freshness threshold (minutes) shared across the UI.
 *
 * Kept in sync with the backend `provider_max_bar_age_minutes` (45). It is intentionally
 * higher than scan-run freshness (30) because delayed/5-minute feeds routinely land
 * ~31 minutes old without being unreliable.
 */
export const FRESH_BAR_MAX_MINUTES = 45;

/** Scan-run freshness threshold — matches backend `health_max_stale_minutes`. */
export const SCAN_FRESH_MAX_MINUTES = 30;

/** Backend freshness flag values that indicate healthy market data. */
export const HEALTHY_FRESHNESS_FLAG_VALUES = new Set(['ok', 'ws_override']);

export function isHealthyFreshnessFlag(value: string): boolean {
  return HEALTHY_FRESHNESS_FLAG_VALUES.has(String(value).trim().toLowerCase());
}

export function hasBadFreshnessFlags(
  flags: Record<string, string> | null | undefined,
): boolean {
  return Object.values(flags ?? {}).some((value) => !isHealthyFreshnessFlag(value));
}
