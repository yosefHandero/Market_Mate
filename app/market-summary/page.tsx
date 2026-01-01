'use client';

import { useMarketData } from '@/components/shared/useMarketData';
import MarketSummary from '@/components/MarketSummary';
import { TableSkeleton } from '@/components/SkeletonLoader';

export default function MarketSummaryPage() {
  const { coins, loading, error } = useMarketData();

  if (loading) {
    return (
      <main className="main-container">
        <div className="space-y-6">
          <TableSkeleton rows={3} />
        </div>
      </main>
    );
  }

  if (error || coins.length === 0) {
    return (
      <main className="main-container">
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-6 text-center">
          <p className="text-red-400">
            {error || 'No market data available. Please try again later.'}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="main-container">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-purple-100">Market Summary</h1>
        <p className="mt-2 text-gray-400">Comprehensive market analysis and sentiment overview</p>
      </div>

      <MarketSummary coins={coins} />
    </main>
  );
}
