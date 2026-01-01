'use client';

import { useMarketData } from '@/components/shared/useMarketData';
import { generateInsights } from '@/lib/insights';
import InsightSection from '@/components/shared/InsightSection';
import { TableSkeleton } from '@/components/SkeletonLoader';
import { Activity } from 'lucide-react';

export default function VolumeSpikesPage() {
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
        <h1 className="text-3xl font-bold text-purple-100">Volume Spikes</h1>
        <p className="mt-2 text-gray-400">Coins with unusually high trading volume</p>
      </div>

      <InsightSection
        title="Volume Spikes"
        description="Coins with unusually high trading volume"
        icon={<Activity className="h-5 w-5 text-yellow-400" />}
        coins={insights.volumeSpikes}
        type="volume_spike"
        showAll={true}
      />
    </main>
  );
}

