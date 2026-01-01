'use client';

import { motion } from 'framer-motion';
import { generateMarketSummary } from '@/lib/market-summary';
import { CoinMarketData } from '@/type';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';

interface MarketSummaryProps {
  coins: CoinMarketData[];
  className?: string;
}

export default function MarketSummary({ coins, className }: MarketSummaryProps) {
  const summary = generateMarketSummary(coins);

  const sentimentIcon = {
    bullish: TrendingUp,
    bearish: TrendingDown,
    neutral: Minus,
  }[summary.sentiment];

  const sentimentColor = {
    bullish: 'text-green-400',
    bearish: 'text-red-400',
    neutral: 'text-gray-400',
  }[summary.sentiment];

  const SentimentIcon = sentimentIcon;

  return (
    <motion.div
      className={cn(
        'rounded-lg border border-purple-100/10 bg-gradient-to-br from-dark-400/80 via-dark-500/60 to-dark-400/80 p-6 backdrop-blur-sm',
        className,
      )}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="mb-4 flex items-center gap-3">
        <div className="rounded-lg bg-purple-600/20 p-2">
          <SentimentIcon className={cn('h-5 w-5', sentimentColor)} />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-purple-100">Market Summary</h3>
          <p className="text-xs text-gray-400 capitalize">{summary.sentiment} sentiment</p>
        </div>
      </div>

      <p className="mb-4 text-base leading-relaxed text-gray-200">{summary.summary}</p>

      {summary.keyTrends.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-purple-100/10 pt-4">
          <p className="text-sm font-medium text-gray-400">Key Trends:</p>
          <ul className="space-y-1">
            {summary.keyTrends.map((trend, index) => (
              <motion.li
                key={index}
                className="flex items-center gap-2 text-sm text-gray-300"
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.1 }}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-purple-400" />
                {trend}
              </motion.li>
            ))}
          </ul>
        </div>
      )}
    </motion.div>
  );
}
