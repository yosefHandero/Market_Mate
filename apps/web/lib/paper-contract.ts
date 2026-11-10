export function formatHoldingDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return 'unavailable';
  if (seconds % 3600 === 0) return `${seconds / 3600} hour${seconds === 3600 ? '' : 's'}`;
  if (seconds % 60 === 0) return `${seconds / 60} minutes`;
  return `${seconds} seconds`;
}

export function forecastAnchor(ticker: string): string {
  return `forecast-${ticker.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

export function formatUnitPrice(price: number | null | undefined): string {
  if (price == null || !Number.isFinite(price) || price <= 0) return '--';
  return price.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    ...(price < 0.01
      ? { minimumSignificantDigits: 1, maximumSignificantDigits: 6 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  });
}

export function formatPaperTimestamp(value: string | null | undefined): string {
  if (!value) return '--';
  // SQLite stores UTC without an offset; explicit provider offsets stay intact.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : '--';
}
