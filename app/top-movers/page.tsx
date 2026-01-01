'use client';

import { useMarketData } from '@/components/shared/useMarketData';
import { generateInsights } from '@/lib/insights';
import InsightSection from '@/components/shared/InsightSection';
import { TableSkeleton } from '@/components/SkeletonLoader';
import { TrendingUp, TrendingDown } from 'lucide-react';

export default function TopMoversPage() {
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

  const insights = generateInsights(coins);

  return (
    <main className="main-container">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-purple-100">Top Movers (24h)</h1>
        <p className="mt-2 text-gray-400">Coins with the highest price increases and declines</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <InsightSection
          title="Top Gainers (24h)"
          description="Coins with the highest price increases"
          icon={<TrendingUp className="h-5 w-5 text-green-400" />}
          coins={insights.topMovers.gainers}
          type="top_mover"
          showAll={true}
        />

        <InsightSection
          title="Top Losers (24h)"
          description="Coins with the largest price declines"
          icon={<TrendingDown className="h-5 w-5 text-red-400" />}
          coins={insights.topMovers.losers}
          type="top_mover"
          showAll={true}
        />
      </div>
    </main>
  );
}
