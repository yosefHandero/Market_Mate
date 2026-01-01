'use client';

import { motion } from 'framer-motion';
import Image from 'next/image';
import Link from 'next/link';
import { formatCurrency, formatPercentage, getTrendInfo } from '@/lib/utils';
import { CoinMarketData } from '@/type';
import { TrendingUp, TrendingDown, Activity, Target, Coins } from 'lucide-react';
import { cn } from '@/lib/utils';

interface InsightCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  coins: CoinMarketData[];
  type: 'top_mover' | 'volume_spike' | 'near_high' | 'whale_accumulation';
  className?: string;
}

function InsightCard({ title, description, icon, coins, type, className }: InsightCardProps) {
  if (coins.length === 0) return null;

  return (
    <motion.div
      className={cn(
        'rounded-lg border border-purple-100/10 bg-gradient-to-br from-dark-400/80 to-dark-500/60 p-6 backdrop-blur-sm',
        className,
      )}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      whileHover={{ y: -2, transition: { duration: 0.2 } }}
    >
      <div className="mb-4 flex items-center gap-3">
        <div className="rounded-lg bg-purple-600/20 p-2">{icon}</div>
        <div>
          <h3 className="text-lg font-semibold text-purple-100">{title}</h3>
          <p className="text-xs text-gray-400">{description}</p>
        </div>
      </div>

      <div className="space-y-2">
        {coins.slice(0, 5).map((coin) => {
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
                    <p className="text-sm font-medium text-white">
                      {formatCurrency(coin.current_price)}
                    </p>
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
        })}
      </div>
    </motion.div>
  );
}

interface InsightsGridProps {
  topMovers: {
    gainers: CoinMarketData[];
    losers: CoinMarketData[];
  };
  volumeSpikes: CoinMarketData[];
  nearHigh: CoinMarketData[];
  whaleSignals: Array<{
    coin: CoinMarketData;
    signalStrength: number;
  }>;
}

export default function InsightsGrid({
  topMovers,
  volumeSpikes,
  nearHigh,
  whaleSignals,
}: InsightsGridProps) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <InsightCard
        title="Top Gainers (24h)"
        description="Coins with the highest price increases"
        icon={<TrendingUp className="h-5 w-5 text-green-400" />}
        coins={topMovers.gainers}
        type="top_mover"
      />

      <InsightCard
        title="Top Losers (24h)"
        description="Coins with the largest price declines"
        icon={<TrendingDown className="h-5 w-5 text-red-400" />}
        coins={topMovers.losers}
        type="top_mover"
      />

      <InsightCard
        title="Volume Spikes"
        description="Coins with unusually high trading volume"
        icon={<Activity className="h-5 w-5 text-yellow-400" />}
        coins={volumeSpikes}
        type="volume_spike"
      />

      <InsightCard
        title="Near 7-Day High"
        description="Coins approaching recent highs"
        icon={<Target className="h-5 w-5 text-blue-400" />}
        coins={nearHigh}
        type="near_high"
      />

      {whaleSignals.length > 0 && (
        <InsightCard
          title="Potential Accumulation"
          description="Signals suggesting whale activity"
          icon={<Coins className="h-5 w-5 text-purple-400" />}
          coins={whaleSignals.map((s) => s.coin)}
          type="whale_accumulation"
        />
      )}
    </div>
  );
}
