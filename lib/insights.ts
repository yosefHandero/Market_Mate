import type { CoinMarketData } from '@/type';

export function getTopMovers(
  coins: CoinMarketData[],
  _period: '1h' | '24h' = '24h',
  count: number = 5,
): {
  gainers: CoinMarketData[];
  losers: CoinMarketData[];
} {
  const sorted = [...coins].sort((a, b) => {
    const aChange = a.price_change_percentage_24h || 0;
    const bChange = b.price_change_percentage_24h || 0;
    return bChange - aChange;
  });

  return {
    gainers: sorted.slice(0, count).filter((c) => (c.price_change_percentage_24h || 0) > 0),
    losers: sorted
      .slice(-count)
      .reverse()
      .filter((c) => (c.price_change_percentage_24h || 0) < 0),
  };
}

export function getVolumeSpikes(
  coins: CoinMarketData[],
  threshold: number = 1.5,
): CoinMarketData[] {
  const totalVolume = coins.reduce((sum, coin) => sum + (coin.total_volume || 0), 0);
  const avgVolume = totalVolume / coins.length;

  return coins
    .filter((coin) => {
      const volume = coin.total_volume || 0;
      return volume > avgVolume * threshold;
    })
    .sort((a, b) => (b.total_volume || 0) - (a.total_volume || 0))
    .slice(0, 10);
}

export function getCoinsNearHigh(
  coins: CoinMarketData[],
  _days: number = 7,
  proximityThreshold: number = 5,
): CoinMarketData[] {
  return coins
    .filter((coin) => {
      const currentPrice = coin.current_price || 0;
      const high24h = coin.high_24h || currentPrice;
      const proximity = ((high24h - currentPrice) / high24h) * 100;
      return proximity <= proximityThreshold && proximity >= 0;
    })
    .sort((a, b) => {
      const aProx =
        ((a.high_24h || a.current_price) - a.current_price) / (a.high_24h || a.current_price);
      const bProx =
        ((b.high_24h || b.current_price) - b.current_price) / (b.high_24h || b.current_price);
      return aProx - bProx;
    });
}

export function getWhaleAccumulationSignals(coins: CoinMarketData[]): Array<{
  coin: CoinMarketData;
  signalStrength: number;
}> {
  return coins
    .map((coin) => {
      const priceChange = coin.price_change_percentage_24h || 0;
      const marketCapChange = coin.market_cap_change_percentage_24h || 0;
      const volume = coin.total_volume || 0;
      const marketCap = coin.market_cap || 1;

      const volumeRatio = volume / marketCap;

      let signalStrength = 0;

      if (priceChange > 0) signalStrength += 30;
      if (priceChange > 5) signalStrength += 20;
      if (marketCapChange > 0) signalStrength += 20;
      if (volumeRatio > 0.1) signalStrength += 15;
      if (volumeRatio > 0.2) signalStrength += 15;

      if (priceChange > 0 && marketCapChange > 0 && volumeRatio > 0.05) {
        signalStrength += 20;
      }

      return {
        coin,
        signalStrength: Math.min(100, signalStrength),
      };
    })
    .filter((item) => item.signalStrength >= 40)
    .sort((a, b) => b.signalStrength - a.signalStrength)
    .slice(0, 10);
}

export function generateInsights(coins: CoinMarketData[]) {
  const topMovers = getTopMovers(coins, '24h', 5);
  const volumeSpikes = getVolumeSpikes(coins, 1.5);
  const nearHigh = getCoinsNearHigh(coins, 7, 5);
  const whaleSignals = getWhaleAccumulationSignals(coins);

  return {
    topMovers,
    volumeSpikes,
    nearHigh,
    whaleSignals,
  };
}
