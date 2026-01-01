'use client';

import { useMarketData } from '@/components/shared/useMarketData';
import { generateInsights } from '@/lib/insights';
import InsightSection from '@/components/shared/InsightSection';
import { TableSkeleton } from '@/components/SkeletonLoader';
import { Coins } from 'lucide-react';

export default function AccumulationPage() {
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

  if (insights.whaleSignals.length === 0) {
    return (
      <main className="main-container">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-purple-100">Potential Accumulation</h1>
          <p className="mt-2 text-gray-400">Signals suggesting whale activity</p>
        </div>

        <div className="rounded-lg border border-purple-100/10 bg-gradient-to-br from-dark-400/80 to-dark-500/60 p-6 backdrop-blur-sm">
          <p className="text-center text-gray-400">
            No accumulation signals detected at this time.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="main-container">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-purple-100">Potential Accumulation</h1>
        <p className="mt-2 text-gray-400">Signals suggesting whale activity</p>
      </div>

      <InsightSection
        title="Potential Accumulation"
        description="Signals suggesting whale activity"
        icon={<Coins className="h-5 w-5 text-purple-400" />}
        coins={insights.whaleSignals.map((s) => s.coin)}
        type="whale_accumulation"
        showAll={true}
      />
    </main>
  );
}
