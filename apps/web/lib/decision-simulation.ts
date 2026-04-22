import type { AssetType, DecisionRow, ScanRun } from '@/lib/types';

export const DEFAULT_SIMULATION_CONFIG = {
  initialCash: 500,
  buyFraction: 0.1,
  minOrderValue: 1,
} as const;

export type SimulationAction = 'buy' | 'sell' | 'hold' | 'blocked';
export type SimulationEligibility = 'eligible' | 'review' | 'blocked' | 'not_applicable';

export interface SimulationConfig {
  initialCash: number;
  buyFraction: number;
  minOrderValue: number;
}

export interface SimulatedPosition {
  symbol: string;
  assetType: AssetType;
  quantity: number;
  price: number | null;
  marketValue: number;
  costBasis: number;
  averageCost: number | null;
  unrealizedPnl: number | null;
}

export interface SimulatedDecisionRow {
  row: DecisionRow;
  eligibility: SimulationEligibility;
  price: number | null;
  simulatedAction: SimulationAction;
  simulatedOrderValue: number | null;
  simulatedQuantity: number | null;
  blockedReason: string | null;
  postTradeCash: number;
  postTradePositionQuantity: number;
  postTradePositionMarketValue: number;
  estimatedPortfolioValue: number;
}

export interface SimulationSummary {
  startingBalance: number;
  currentCash: number;
  investedValue: number;
  totalEstimatedPortfolioValue: number;
  openSimulatedPositions: number;
  totalUnrealizedPnl: number | null;
  buyCount: number;
  sellCount: number;
  blockedCount: number;
  positions: SimulatedPosition[];
}

export interface DecisionSimulationResult {
  rows: SimulatedDecisionRow[];
  summary: SimulationSummary;
  config: SimulationConfig;
}

type PositionState = {
  symbol: string;
  assetType: AssetType;
  quantity: number;
  costBasis: number;
};

function buildPriceKey(symbol: string, assetType: AssetType) {
  return `${assetType}:${symbol}`.toUpperCase();
}

export function roundCurrency(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export function roundQuantity(value: number) {
  return Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
}

function normalizeEligibility(row: DecisionRow): SimulationEligibility {
  if (row.execution_eligibility === 'eligible') return 'eligible';
  if (row.execution_eligibility === 'review') return 'review';
  if (row.execution_eligibility === 'not_applicable') return 'not_applicable';
  if (row.execution_eligibility === 'blocked') return 'blocked';
  return row.signal === 'HOLD' ? 'not_applicable' : 'blocked';
}

function blockedReasonForEligibility(eligibility: SimulationEligibility) {
  if (eligibility === 'review') return 'Operational eligibility is review.';
  if (eligibility === 'not_applicable') return 'Operational eligibility is not applicable.';
  return 'Operational eligibility is blocked.';
}

function getPriceForRow(
  priceMap: Record<string, number>,
  row: Pick<DecisionRow, 'symbol' | 'asset_type'>,
) {
  const value = priceMap[buildPriceKey(row.symbol, row.asset_type)];
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value;
}

function summarizePositions(
  positions: Map<string, PositionState>,
  priceMap: Record<string, number>,
): Pick<SimulationSummary, 'investedValue' | 'openSimulatedPositions' | 'totalUnrealizedPnl' | 'positions'> {
  const summaryPositions: SimulatedPosition[] = [];

  for (const position of positions.values()) {
    if (position.quantity <= 0) continue;
    const price =
      priceMap[buildPriceKey(position.symbol, position.assetType)] &&
      Number.isFinite(priceMap[buildPriceKey(position.symbol, position.assetType)])
        ? priceMap[buildPriceKey(position.symbol, position.assetType)]
        : null;
    const marketValue = price == null ? 0 : roundCurrency(position.quantity * price);
    const averageCost =
      position.quantity > 0 ? roundCurrency(position.costBasis / position.quantity) : null;
    const unrealizedPnl = price == null ? null : roundCurrency(marketValue - position.costBasis);

    summaryPositions.push({
      symbol: position.symbol,
      assetType: position.assetType,
      quantity: position.quantity,
      price,
      marketValue,
      costBasis: position.costBasis,
      averageCost,
      unrealizedPnl,
    });
  }

  const investedValue = roundCurrency(
    summaryPositions.reduce((sum, position) => sum + position.marketValue, 0),
  );
  const pricedPnls = summaryPositions
    .map((position) => position.unrealizedPnl)
    .filter((value): value is number => value != null);

  return {
    investedValue,
    openSimulatedPositions: summaryPositions.length,
    totalUnrealizedPnl: pricedPnls.length
      ? roundCurrency(pricedPnls.reduce((sum, value) => sum + value, 0))
      : null,
    positions: summaryPositions,
  };
}

export function buildDecisionPriceMap(scan: ScanRun | null | undefined): Record<string, number> {
  if (!scan) return {};

  return scan.results.reduce<Record<string, number>>((acc, result) => {
    if (Number.isFinite(result.price) && result.price > 0) {
      acc[buildPriceKey(result.ticker, result.asset_type)] = result.price;
    }
    return acc;
  }, {});
}

export function simulateDecisionPortfolio(
  rows: DecisionRow[],
  priceMap: Record<string, number>,
  config: Partial<SimulationConfig> = {},
): DecisionSimulationResult {
  const resolvedConfig: SimulationConfig = {
    initialCash: config.initialCash ?? DEFAULT_SIMULATION_CONFIG.initialCash,
    buyFraction: config.buyFraction ?? DEFAULT_SIMULATION_CONFIG.buyFraction,
    minOrderValue: config.minOrderValue ?? DEFAULT_SIMULATION_CONFIG.minOrderValue,
  };
  const positions = new Map<string, PositionState>();
  const simulatedRows: SimulatedDecisionRow[] = [];
  let cash = roundCurrency(resolvedConfig.initialCash);
  let buyCount = 0;
  let sellCount = 0;
  let blockedCount = 0;

  for (const row of rows) {
    const price = getPriceForRow(priceMap, row);
    const eligibility = normalizeEligibility(row);
    const key = buildPriceKey(row.symbol, row.asset_type);
    let simulatedAction: SimulationAction = 'hold';
    let simulatedOrderValue: number | null = null;
    let simulatedQuantity: number | null = null;
    let blockedReason: string | null = null;

    if (row.signal === 'HOLD') {
      simulatedAction = 'hold';
    } else if (eligibility !== 'eligible') {
      simulatedAction = 'blocked';
      blockedReason = blockedReasonForEligibility(eligibility);
      blockedCount += 1;
    } else if (row.signal === 'BUY') {
      const orderValue = roundCurrency(cash * resolvedConfig.buyFraction);

      if (price == null) {
        simulatedAction = 'blocked';
        blockedReason = 'Latest scan price is unavailable.';
        blockedCount += 1;
      } else if (orderValue < resolvedConfig.minOrderValue) {
        simulatedAction = 'blocked';
        blockedReason = `Available cash is below the $${resolvedConfig.minOrderValue.toFixed(2)} minimum simulated order.`;
        blockedCount += 1;
      } else {
        const quantity = roundQuantity(orderValue / price);

        if (quantity <= 0) {
          simulatedAction = 'blocked';
          blockedReason = 'Calculated quantity is too small to simulate.';
          blockedCount += 1;
        } else {
          const existing = positions.get(key);
          const nextQuantity = roundQuantity((existing?.quantity ?? 0) + quantity);
          const nextCostBasis = roundCurrency((existing?.costBasis ?? 0) + orderValue);

          positions.set(key, {
            symbol: row.symbol,
            assetType: row.asset_type,
            quantity: nextQuantity,
            costBasis: nextCostBasis,
          });
          cash = roundCurrency(cash - orderValue);
          simulatedAction = 'buy';
          simulatedOrderValue = orderValue;
          simulatedQuantity = quantity;
          buyCount += 1;
        }
      }
    } else if (row.signal === 'SELL') {
      const existing = positions.get(key);

      if (!existing || existing.quantity <= 0) {
        simulatedAction = 'blocked';
        blockedReason = 'No simulated position is open for this symbol.';
        blockedCount += 1;
      } else if (price == null) {
        simulatedAction = 'blocked';
        blockedReason = 'Latest scan price is unavailable.';
        blockedCount += 1;
      } else {
        const orderValue = roundCurrency(existing.quantity * price);
        const quantity = existing.quantity;

        cash = roundCurrency(cash + orderValue);
        positions.delete(key);
        simulatedAction = 'sell';
        simulatedOrderValue = orderValue;
        simulatedQuantity = quantity;
        sellCount += 1;
      }
    }

    const currentPosition = positions.get(key);
    const positionPrice = currentPosition ? getPriceForRow(priceMap, row) : null;
    const postTradePositionQuantity = currentPosition?.quantity ?? 0;
    const postTradePositionMarketValue =
      currentPosition && positionPrice != null
        ? roundCurrency(currentPosition.quantity * positionPrice)
        : 0;
    const portfolioSnapshot = summarizePositions(positions, priceMap);

    simulatedRows.push({
      row,
      eligibility,
      price,
      simulatedAction,
      simulatedOrderValue,
      simulatedQuantity,
      blockedReason,
      postTradeCash: cash,
      postTradePositionQuantity,
      postTradePositionMarketValue,
      estimatedPortfolioValue: roundCurrency(cash + portfolioSnapshot.investedValue),
    });
  }

  const finalSnapshot = summarizePositions(positions, priceMap);

  return {
    rows: simulatedRows,
    summary: {
      startingBalance: roundCurrency(resolvedConfig.initialCash),
      currentCash: cash,
      investedValue: finalSnapshot.investedValue,
      totalEstimatedPortfolioValue: roundCurrency(cash + finalSnapshot.investedValue),
      openSimulatedPositions: finalSnapshot.openSimulatedPositions,
      totalUnrealizedPnl: finalSnapshot.totalUnrealizedPnl,
      buyCount,
      sellCount,
      blockedCount,
      positions: finalSnapshot.positions,
    },
    config: resolvedConfig,
  };
}
