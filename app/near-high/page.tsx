'use client';

import { useMarketData } from '@/components/shared/useMarketData';
import { generateInsights } from '@/lib/insights';
import InsightSection from '@/components/shared/InsightSection';
import { TableSkeleton } from '@/components/SkeletonLoader';
import { Target } from 'lucide-react';

export default function NearHighPage() {
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
        <h1 className="text-3xl font-bold text-purple-100">Near 7-Day High</h1>
        <p className="mt-2 text-gray-400">Coins approaching recent highs</p>
      </div>

      <InsightSection
        title="Near 7-Day High"
        description="Coins approaching recent highs"
        icon={<Target className="h-5 w-5 text-blue-400" />}
        coins={insights.nearHigh}
        type="near_high"
        showAll={true}
      />
    </main>
  );
}
