/**
 * Market Intelligence & Insights Engine
 * Generates actionable insights from market data
 */

// Using global type definitions from type.d.ts
// Types are available globally, no import needed

/**
 * Find top movers (gainers/losers) in a given time period
 */
export function getTopMovers(
  coins: CoinMarketData[],
  _period: '1h' | '24h' = '24h',
  count: number = 5,
): {
  gainers: CoinMarketData[];
  losers: CoinMarketData[];
} {
  // For 1h, we'd need price_change_percentage_1h_in_currency
  // For now, using 24h data as approximation
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

/**
 * Detect coins with significant volume spikes
 * Volume spike = current volume significantly higher than average
 */
export function getVolumeSpikes(
  coins: CoinMarketData[],
  threshold: number = 1.5,
): CoinMarketData[] {
  // Calculate average volume
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

/**
 * Find coins near their 7-day high
 * Proximity is a percentage (0-100) indicating how close to the high
 */
export function getCoinsNearHigh(
  coins: CoinMarketData[],
  _days: number = 7,
  proximityThreshold: number = 5,
): CoinMarketData[] {
  // Using high_24h as approximation (in real scenario, would use 7d high from historical data)
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

/**
 * Detect potential whale accumulation signals
 * Signal = Volume ↑ + Price ↑ + Market Cap ↑
 */
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

      // Calculate volume ratio (higher = more significant)
      const volumeRatio = volume / marketCap;

      // Signal strength calculation
      // Positive price change + positive market cap change + high volume = accumulation
      let signalStrength = 0;

      if (priceChange > 0) signalStrength += 30;
      if (priceChange > 5) signalStrength += 20; // Strong price increase
      if (marketCapChange > 0) signalStrength += 20;
      if (volumeRatio > 0.1) signalStrength += 15; // High volume relative to market cap
      if (volumeRatio > 0.2) signalStrength += 15; // Very high volume

      // Bonus for consistent positive movement
      if (priceChange > 0 && marketCapChange > 0 && volumeRatio > 0.05) {
        signalStrength += 20;
      }

      return {
        coin,
        signalStrength: Math.min(100, signalStrength),
      };
    })
    .filter((item) => item.signalStrength >= 40) // Only show signals above threshold
    .sort((a, b) => b.signalStrength - a.signalStrength)
    .slice(0, 10);
}

/**
 * Generate all insights from market data
 */
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
