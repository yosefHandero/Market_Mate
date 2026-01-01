'use client';

import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Image from 'next/image';
import { formatCurrency, formatPercentage, getTrendInfo } from '@/lib/utils';
import { CoinMarketData } from '@/type';
import { Button } from '@/components/ui/button';
import { X, TrendingUp } from 'lucide-react';
import { cn } from '@/lib/utils';

interface CoinComparisonProps {
  availableCoins: CoinMarketData[];
  maxSelection?: number;
  className?: string;
}

export default function CoinComparison({
  availableCoins,
  maxSelection = 3,
  className,
}: CoinComparisonProps) {
  const [selectedCoins, setSelectedCoins] = useState<string[]>([]);

  const comparisonData = useMemo(() => {
    const coins = availableCoins.filter((c) => selectedCoins.includes(c.id));

    if (coins.length < 2) return null;

    let bestPerformer = coins[0].id;
    let worstPerformer = coins[0].id;
    let bestChange = coins[0].price_change_percentage_24h || 0;
    let worstChange = coins[0].price_change_percentage_24h || 0;

    coins.forEach((coin) => {
      const change = coin.price_change_percentage_24h || 0;
      if (change > bestChange) {
        bestChange = change;
        bestPerformer = coin.id;
      }
      if (change < worstChange) {
        worstChange = change;
        worstPerformer = coin.id;
      }
    });

    return {
      coins,
      bestPerformer,
      worstPerformer,
    };
  }, [availableCoins, selectedCoins]);

  const toggleCoin = (coinId: string) => {
    setSelectedCoins((prev) => {
      if (prev.includes(coinId)) {
        return prev.filter((id) => id !== coinId);
      }
      if (prev.length >= maxSelection) {
        return prev;
      }
      return [...prev, coinId];
    });
  };

  const removeCoin = (coinId: string) => {
    setSelectedCoins((prev) => prev.filter((id) => id !== coinId));
  };

  return (
    <div className={cn('space-y-4', className)}>
      <div>
        <h3 className="mb-2 text-lg font-semibold text-purple-100">Compare Coins</h3>
        <p className="text-sm text-gray-400">
          Select up to {maxSelection} coins to compare their performance
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {availableCoins.slice(0, 20).map((coin) => {
          const isSelected = selectedCoins.includes(coin.id);
          const isDisabled = !isSelected && selectedCoins.length >= maxSelection;

          return (
            <Button
              key={coin.id}
              variant="outline"
              size="sm"
              onClick={() => toggleCoin(coin.id)}
              disabled={isDisabled}
              className={cn(
                'h-auto gap-2 px-3 py-2',
                isSelected && 'bg-purple-600/20 border-purple-400',
                isDisabled && 'opacity-50 cursor-not-allowed',
              )}
            >
              <Image src={coin.image} alt={coin.name} width={20} height={20} />
              <span className="text-sm">{coin.symbol.toUpperCase()}</span>
              {isSelected && (
                <X
                  className="h-3 w-3"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeCoin(coin.id);
                  }}
                />
              )}
            </Button>
          );
        })}
      </div>

      <AnimatePresence>
        {comparisonData && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden rounded-lg border border-purple-100/10 bg-dark-400/50"
          >
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-purple-100/10">
                    <th className="px-4 py-3 text-left text-sm font-medium text-purple-100">
                      Coin
                    </th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-purple-100">
                      Price
                    </th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-purple-100">
                      24h Change
                    </th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-purple-100">
                      Market Cap
                    </th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-purple-100">
                      Volume
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {comparisonData.coins.map((coin) => {
                    const trend = getTrendInfo(coin.price_change_percentage_24h);
                    const isBest = coin.id === comparisonData.bestPerformer;
                    const TrendIcon = trend.icon;

                    return (
                      <motion.tr
                        key={coin.id}
                        className={cn(
                          'border-b border-purple-100/5 transition-colors',
                          isBest && 'bg-green-500/5',
                        )}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2 }}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Image src={coin.image} alt={coin.name} width={24} height={24} />
                            <div>
                              <div className="flex items-center gap-1">
                                <span className="text-sm font-medium text-white">{coin.name}</span>
                                {isBest && (
                                  <span title="Best Performer">
                                    <TrendingUp className="h-3 w-3 text-green-400" />
                                  </span>
                                )}
                              </div>
                              <span className="text-xs text-gray-400">
                                {coin.symbol.toUpperCase()}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right text-sm text-white">
                          {formatCurrency(coin.current_price)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div
                            className={cn('flex items-center justify-end gap-1', trend.textClass)}
                          >
                            <TrendIcon className="h-3 w-3" />
                            <span className="text-sm font-medium">
                              {formatPercentage(coin.price_change_percentage_24h)}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right text-sm text-gray-300">
                          {formatCurrency(coin.market_cap, 0)}
                        </td>
                        <td className="px-4 py-3 text-right text-sm text-gray-300">
                          {formatCurrency(coin.total_volume, 0)}
                        </td>
                      </motion.tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {selectedCoins.length < 2 && (
        <p className="text-center text-sm text-gray-400">Select at least 2 coins to compare</p>
      )}
    </div>
  );
}
