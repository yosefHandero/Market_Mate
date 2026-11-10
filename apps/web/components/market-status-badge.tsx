import type { ScanMarketStatus } from '@/lib/types';

export function MarketStatusBadge({ status }: { status: ScanMarketStatus }) {
  const cls = status === 'bullish' ? 'green' : status === 'bearish' ? 'red' : 'amber';
  return <span className={`badge ${cls}`}>Market: {status}</span>;
}
