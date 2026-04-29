import { readErrorMessage } from '@/lib/scanner-api';
import type {
  DecisionSignal,
  OrderPlaceRequest,
  OrderPlaceResponse,
  OrderPreviewRequest,
  OrderPreviewResponse,
  PaperLedgerSummary,
  PaperPositionSummary,
  ScanResult,
  ScanRun,
} from '@/lib/types';

export interface PricePoint {
  timestamp: string;
  price: number;
}

export interface RiskOverlayState {
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  accountSize: number;
  riskPercent: number;
}

export interface RiskMetrics {
  structureValid: boolean;
  triggerPrice: number;
  rewardMultiple: number | null;
  recommendedPositionSize: number | null;
  openRisk: number | null;
  currentPnl: number;
  currentPnlSource: 'paper' | 'scenario';
  totalOpenQuantity: number;
  plannedNotional: number | null;
  rewardAmount: number | null;
  riskPerUnit: number;
  rewardPerUnit: number;
}

export async function previewOrder(payload: OrderPreviewRequest): Promise<OrderPreviewResponse> {
  const response = await fetch('/api/orders/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as OrderPreviewResponse;
}

export async function placeOrder(payload: OrderPlaceRequest): Promise<OrderPlaceResponse> {
  const response = await fetch('/api/orders/place', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(payload.idempotency_key ? { 'X-Idempotency-Key': payload.idempotency_key } : {}),
    },
    body: JSON.stringify({ ...payload, mode: 'dry_run', dry_run: true }),
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as OrderPlaceResponse;
}

export async function getPaperLedger({
  limit = 100,
  offset = 0,
  symbol,
  status,
}: {
  limit?: number;
  offset?: number;
  symbol?: string | null;
  status?: 'open' | 'closed' | null;
} = {}): Promise<PaperPositionSummary[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (symbol) params.set('symbol', symbol);
  if (status) params.set('status', status);

  const response = await fetch(`/api/paper/ledger?${params.toString()}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as PaperPositionSummary[];
}

export async function getPaperLedgerSummary(): Promise<PaperLedgerSummary> {
  const response = await fetch('/api/paper/ledger/summary', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as PaperLedgerSummary;
}

function roundPrice(value: number) {
  return Math.round(value * 100) / 100;
}

function parseTimestamp(value: string): number | null {
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function defaultDirection(signal: DecisionSignal) {
  return signal === 'SELL' ? 'short' : 'long';
}

export function deriveInitialOverlay(result: ScanResult): RiskOverlayState {
  const baseRange = Math.max(
    result.price * 0.008,
    Math.abs(result.price_change_pct / 100) * result.price * 0.85,
    0.25,
  );
  const direction = defaultDirection(result.decision_signal);

  if (direction === 'short') {
    return {
      entryPrice: roundPrice(result.price),
      stopLoss: roundPrice(result.price + baseRange),
      takeProfit: roundPrice(Math.max(0.01, result.price - baseRange * 2)),
      accountSize: 25_000,
      riskPercent: 1,
    };
  }

  return {
    entryPrice: roundPrice(result.price),
    stopLoss: roundPrice(Math.max(0.01, result.price - baseRange)),
    takeProfit: roundPrice(result.price + baseRange * 2),
    accountSize: 25_000,
    riskPercent: 1,
  };
}

export function buildTickerPriceSeries(
  history: ScanRun[],
  latestScan: ScanRun | null,
  ticker: string,
): PricePoint[] {
  const runs = [...history];
  if (
    latestScan &&
    !runs.some(
      (run) => run.run_id === latestScan.run_id || run.created_at === latestScan.created_at,
    )
  ) {
    runs.push(latestScan);
  }

  const points = runs
    .sort(
      (left, right) =>
        (parseTimestamp(left.created_at) ?? 0) - (parseTimestamp(right.created_at) ?? 0),
    )
    .flatMap((run) => {
      const match = run.results.find((result) => result.ticker === ticker);
      return match
        ? [
            {
              timestamp: run.created_at,
              price: match.price,
            },
          ]
        : [];
    })
    .filter((point, index, all) => {
      const firstMatch = all.findIndex(
        (candidate) => candidate.timestamp === point.timestamp && candidate.price === point.price,
      );
      return firstMatch === index;
    });

  if (points.length >= 3) {
    return points;
  }

  const fallbackResult =
    latestScan?.results.find((result) => result.ticker === ticker) ??
    history.flatMap((run) => run.results).find((result) => result.ticker === ticker);

  return fallbackResult ? buildSyntheticPriceSeries(fallbackResult) : points;
}

export function buildSyntheticPriceSeries(result: ScanResult): PricePoint[] {
  const pointCount = 12;
  const anchorPrice =
    result.price_change_pct === -100
      ? result.price
      : result.price / Math.max(0.1, 1 + result.price_change_pct / 100);
  const waveSize = Math.max(result.price * 0.006, 0.12) * (1 + result.relative_volume * 0.1);
  const createdAt = parseTimestamp(result.created_at) ?? Date.now();

  return Array.from({ length: pointCount }, (_, index) => {
    const progress = index / (pointCount - 1);
    const trend = anchorPrice + (result.price - anchorPrice) * progress;
    const wave = Math.sin(progress * Math.PI * 3) * waveSize * (1 - progress * 0.35);
    const price = index === pointCount - 1 ? result.price : Math.max(0.01, trend + wave);

    return {
      timestamp: new Date(createdAt - (pointCount - 1 - index) * 5 * 60_000).toISOString(),
      price: roundPrice(price),
    };
  });
}

export function calculateRiskMetrics({
  overlay,
  signal,
  triggerPrice,
  paperPositions,
  ticker,
}: {
  overlay: RiskOverlayState;
  signal: DecisionSignal;
  triggerPrice: number;
  paperPositions: PaperPositionSummary[];
  ticker: string;
}): RiskMetrics {
  const directionMultiplier = signal === 'SELL' ? -1 : 1;
  const riskPerUnit = Math.abs(overlay.entryPrice - overlay.stopLoss);
  const rewardPerUnit = Math.abs(overlay.takeProfit - overlay.entryPrice);
  const rewardMultiple = riskPerUnit > 0 ? rewardPerUnit / riskPerUnit : null;
  const recommendedPositionSize =
    riskPerUnit > 0 ? (overlay.accountSize * (overlay.riskPercent / 100)) / riskPerUnit : null;

  const activePaperPositions = paperPositions.filter(
    (position) => position.status === 'open' && position.ticker === ticker,
  );
  const totalOpenQuantity = activePaperPositions.reduce(
    (sum, position) => sum + position.quantity,
    0,
  );
  const effectiveQuantity = totalOpenQuantity || recommendedPositionSize || 0;

  const currentPnlFromPaper = activePaperPositions.reduce((sum, position) => {
    const sideMultiplier = position.side === 'buy' ? 1 : -1;
    return (
      sum + (triggerPrice - position.simulated_fill_price) * position.quantity * sideMultiplier
    );
  }, 0);
  const currentPnlFromScenario =
    (triggerPrice - overlay.entryPrice) * effectiveQuantity * directionMultiplier;

  const structureValid =
    signal === 'SELL'
      ? overlay.takeProfit <= overlay.entryPrice && overlay.stopLoss >= overlay.entryPrice
      : overlay.takeProfit >= overlay.entryPrice && overlay.stopLoss <= overlay.entryPrice;

  return {
    structureValid,
    triggerPrice,
    rewardMultiple,
    recommendedPositionSize,
    openRisk: riskPerUnit > 0 ? riskPerUnit * effectiveQuantity : null,
    currentPnl:
      totalOpenQuantity > 0 ? roundPrice(currentPnlFromPaper) : roundPrice(currentPnlFromScenario),
    currentPnlSource: totalOpenQuantity > 0 ? 'paper' : 'scenario',
    totalOpenQuantity,
    plannedNotional:
      recommendedPositionSize != null
        ? roundPrice(overlay.entryPrice * recommendedPositionSize)
        : null,
    rewardAmount:
      recommendedPositionSize != null ? roundPrice(rewardPerUnit * recommendedPositionSize) : null,
    riskPerUnit: roundPrice(riskPerUnit),
    rewardPerUnit: roundPrice(rewardPerUnit),
  };
}
