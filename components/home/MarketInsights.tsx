'use client';

import { useMarketData } from '@/components/shared/useMarketData';
import { generateInsights } from '@/lib/insights';
import MarketSummary from '@/components/MarketSummary';
import InsightPreview from './InsightPreview';
import { TableSkeleton } from '@/components/SkeletonLoader';
import { TrendingUp, TrendingDown, Activity, Target, Coins } from 'lucide-react';
import Link from 'next/link';
import Image from 'next/image';
import { formatCurrency, formatPercentage, getTrendInfo } from '@/lib/utils';
import { cn } from '@/lib/utils';

export default function MarketInsights() {
  const { coins, loading, error } = useMarketData();

  if (loading) {
    return (
      <div className="space-y-6">
        <TableSkeleton rows={3} />
      </div>
    );
  }

  if (error || coins.length === 0) {
    return null;
  }

  const insights = generateInsights(coins);

  const renderCoinPreview = (
    coin: (typeof coins)[0],
    type?: 'volume_spike' | 'whale_accumulation',
  ) => {
    const trend = getTrendInfo(coin.price_change_percentage_24h);
    const TrendIcon = trend.icon;

    return (
      <Link
        key={coin.id}
        href={`/coins/${coin.id}`}
        className="block rounded-md bg-dark-500/30 p-3 transition-colors hover:bg-dark-500/50"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Image src={coin.image} alt={coin.name} width={32} height={32} />
            <div>
              <p className="text-sm font-medium text-white">{coin.name}</p>
              <p className="text-xs text-gray-400">{coin.symbol.toUpperCase()}</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-sm font-medium text-white">{formatCurrency(coin.current_price)}</p>
              <div className={cn('flex items-center gap-1 text-xs', trend.textClass)}>
                <TrendIcon className="h-3 w-3" />
                <span>{formatPercentage(coin.price_change_percentage_24h)}</span>
              </div>
            </div>
            {type === 'volume_spike' && (
              <div className="text-right text-xs text-gray-400">
                Vol: {formatCurrency(coin.total_volume, 0)}
              </div>
            )}
            {type === 'whale_accumulation' && (
              <div className="text-right text-xs text-gray-400">
                Cap: {formatCurrency(coin.market_cap, 0)}
              </div>
            )}
          </div>
        </div>
      </Link>
    );
  };

  return (
    <div className="space-y-6">
      <Link href="/market-summary" className="block">
        <MarketSummary
          coins={coins}
          className="cursor-pointer transition-opacity hover:opacity-90"
        />
      </Link>

      <div className="grid gap-6 md:grid-cols-2">
        <InsightPreview
          title="Top Gainers (24h)"
          description="Coins with the highest price increases"
          icon={<TrendingUp className="h-5 w-5 text-green-400" />}
          href="/top-movers"
        >
          <div className="space-y-2">
            {insights.topMovers.gainers.slice(0, 3).map((coin) => renderCoinPreview(coin))}
          </div>
        </InsightPreview>

        <InsightPreview
          title="Top Losers (24h)"
          description="Coins with the largest price declines"
          icon={<TrendingDown className="h-5 w-5 text-red-400" />}
          href="/top-movers"
        >
          <div className="space-y-2">
            {insights.topMovers.losers.slice(0, 3).map((coin) => renderCoinPreview(coin))}
          </div>
        </InsightPreview>

        <InsightPreview
          title="Volume Spikes"
          description="Coins with unusually high trading volume"
          icon={<Activity className="h-5 w-5 text-yellow-400" />}
          href="/volume-spikes"
        >
          <div className="space-y-2">
            {insights.volumeSpikes
              .slice(0, 3)
              .map((coin) => renderCoinPreview(coin, 'volume_spike'))}
          </div>
        </InsightPreview>

        <InsightPreview
          title="Near 7-Day High"
          description="Coins approaching recent highs"
          icon={<Target className="h-5 w-5 text-blue-400" />}
          href="/near-high"
        >
          <div className="space-y-2">
            {insights.nearHigh.slice(0, 3).map((coin) => renderCoinPreview(coin))}
          </div>
        </InsightPreview>

        {insights.whaleSignals.length > 0 && (
          <InsightPreview
            title="Potential Accumulation"
            description="Signals suggesting whale activity"
            icon={<Coins className="h-5 w-5 text-purple-400" />}
            href="/accumulation"
          >
            <div className="space-y-2">
              {insights.whaleSignals
                .map((s) => s.coin)
                .slice(0, 3)
                .map((coin) => renderCoinPreview(coin, 'whale_accumulation'))}
            </div>
          </InsightPreview>
        )}
      </div>
    </div>
  );
}
