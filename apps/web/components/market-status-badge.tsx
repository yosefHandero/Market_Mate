import type { MarketStatus } from '@/lib/types';

export function MarketStatusBadge({ status }: { status: MarketStatus }) {
  const cls = status === 'bullish' ? 'green' : status === 'bearish' ? 'red' : 'amber';
  return <span className={`badge ${cls}`}>Market: {status}</span>;
}
