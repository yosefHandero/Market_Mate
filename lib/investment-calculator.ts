import { InvestmentResult } from '@/type';

export function calculateInvestment(
  initialInvestment: number,
  historicalPrice: number,
  currentPrice: number,
): InvestmentResult {
  if (historicalPrice <= 0 || currentPrice <= 0) {
    return {
      initialInvestment,
      currentValue: initialInvestment,
      gainLoss: 0,
      gainLossPercentage: 0,
      isProfit: false,
    };
  }

  const shares = initialInvestment / historicalPrice;
  const currentValue = shares * currentPrice;
  const gainLoss = currentValue - initialInvestment;
  const gainLossPercentage = (gainLoss / initialInvestment) * 100;
  const isProfit = gainLoss > 0;

  return {
    initialInvestment,
    currentValue,
    gainLoss,
    gainLossPercentage,
    isProfit,
  };
}

export function formatInvestmentResult(result: InvestmentResult) {
  return {
    ...result,
    currentValueFormatted: `$${result.currentValue.toFixed(2)}`,
    gainLossFormatted: `${result.isProfit ? '+' : ''}$${result.gainLoss.toFixed(2)}`,
    gainLossPercentageFormatted: `${result.isProfit ? '+' : ''}${result.gainLossPercentage.toFixed(2)}%`,
  };
}
