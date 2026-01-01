'use client';

import { motion } from 'framer-motion';
import Image from 'next/image';
import Link from 'next/link';
import { formatCurrency, formatPercentage, getTrendInfo } from '@/lib/utils';
import { CoinMarketData } from '@/type';
import { cn } from '@/lib/utils';

interface InsightSectionProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  coins: CoinMarketData[];
  type: 'top_mover' | 'volume_spike' | 'near_high' | 'whale_accumulation';
  showAll?: boolean;
  maxItems?: number;
  className?: string;
}

export default function InsightSection({
  title,
  description,
  icon,
  coins,
  type,
  showAll = false,
  maxItems = 5,
  className,
}: InsightSectionProps) {
  if (coins.length === 0) return null;

  const displayCoins = showAll ? coins : coins.slice(0, maxItems);

  return (
    <motion.div
      className={cn(
        'rounded-lg border border-purple-100/10 bg-gradient-to-br from-dark-400/80 to-dark-500/60 p-6 backdrop-blur-sm',
        className,
      )}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="mb-4 flex items-center gap-3">
        <div className="rounded-lg bg-purple-600/20 p-2">{icon}</div>
        <div>
          <h3 className="text-lg font-semibold text-purple-100">{title}</h3>
          <p className="text-xs text-gray-400">{description}</p>
        </div>
      </div>

      <div className="space-y-2">
        {displayCoins.map((coin) => {
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

