'use client';

import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { calculateInvestment, formatInvestmentResult } from '@/lib/investment-calculator';
import { formatCurrency } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { cn } from '@/lib/utils';

interface InvestmentCalculatorProps {
  currentPrice: number;
  historicalPrice?: number;
  defaultInvestment?: number;
  className?: string;
}

/**
 * "If You Invested $100" Calculator Component
 * Calculates returns on hypothetical investments
 */
export default function InvestmentCalculator({
  currentPrice,
  historicalPrice,
  defaultInvestment = 100,
  className,
}: InvestmentCalculatorProps) {
  const [investmentAmount, setInvestmentAmount] = useState(defaultInvestment);
  const [historicalPriceInput, setHistoricalPriceInput] = useState(
    historicalPrice?.toString() || '',
  );

  const result = useMemo(() => {
    const histPrice = parseFloat(historicalPriceInput) || currentPrice;
    if (histPrice <= 0 || currentPrice <= 0) return null;

    const calc = calculateInvestment(investmentAmount, histPrice, currentPrice);
    return formatInvestmentResult(calc);
  }, [investmentAmount, historicalPriceInput, currentPrice]);

  return (
    <motion.div
      className={cn('rounded-lg border border-purple-100/10 bg-dark-400/50 p-6', className)}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <h3 className="mb-4 text-lg font-semibold text-purple-100">Investment Calculator</h3>
      <p className="mb-4 text-sm text-gray-400">See what your investment would be worth today</p>

      <div className="space-y-4">
        <div>
          <label className="mb-2 block text-sm text-gray-300">Investment Amount</label>
          <Input
            type="number"
            value={investmentAmount}
            onChange={(e) => setInvestmentAmount(parseFloat(e.target.value) || 0)}
            className="bg-dark-500 text-white"
            min="1"
            step="1"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm text-gray-300">Historical Price (USD)</label>
          <Input
            type="number"
            value={historicalPriceInput}
            onChange={(e) => setHistoricalPriceInput(e.target.value)}
            className="bg-dark-500 text-white"
            min="0.000001"
            step="0.000001"
            placeholder={currentPrice.toString()}
          />
        </div>

        {result && (
          <motion.div
            className="mt-6 rounded-lg bg-dark-500/50 p-4"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.2 }}
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">Initial Investment</span>
                <span className="font-medium text-white">
                  {formatCurrency(result.initialInvestment)}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">Current Value</span>
                <span className="text-lg font-bold text-white">{result.currentValueFormatted}</span>
              </div>

              <div className="flex items-center justify-between border-t border-purple-100/10 pt-3">
                <span className="text-sm text-gray-400">Gain/Loss</span>
                <div className="flex items-center gap-2">
                  {result.isProfit ? (
                    <TrendingUp className="h-4 w-4 text-green-400" />
                  ) : (
                    <TrendingDown className="h-4 w-4 text-red-400" />
                  )}
                  <span
                    className={cn(
                      'text-lg font-bold',
                      result.isProfit ? 'text-green-400' : 'text-red-400',
                    )}
                  >
                    {result.gainLossFormatted}
                  </span>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">Return</span>
                <span
                  className={cn(
                    'text-lg font-semibold',
                    result.isProfit ? 'text-green-400' : 'text-red-400',
                  )}
                >
                  {result.gainLossPercentageFormatted}
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
