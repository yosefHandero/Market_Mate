import type { CoinMarketData } from '@/type';
import {
  getTopMovers,
  getVolumeSpikes,
  getCoinsNearHigh,
  getWhaleAccumulationSignals,
} from './insights';

interface MarketSummary {
  summary: string;
  sentiment: 'bullish' | 'bearish' | 'neutral';
  keyTrends: string[];
}

export function generateMarketSummary(coins: CoinMarketData[]): MarketSummary {
  if (!coins || coins.length === 0) {
    return {
      summary: 'Market data is currently unavailable.',
      sentiment: 'neutral',
      keyTrends: [],
    };
  }

  const topMovers = getTopMovers(coins, '24h', 5);
  const volumeSpikes = getVolumeSpikes(coins, 1.5);
  const nearHigh = getCoinsNearHigh(coins, 7, 5);
  const whaleSignals = getWhaleAccumulationSignals(coins);

  const avgPriceChange =
    coins.reduce((sum, coin) => sum + (coin.price_change_percentage_24h || 0), 0) / coins.length;
  const gainers = coins.filter((c) => (c.price_change_percentage_24h || 0) > 0).length;
  const gainerRatio = gainers / coins.length;

  const bitcoin = coins.find((c) => c.id === 'bitcoin' || c.symbol === 'btc');
  const ethereum = coins.find((c) => c.id === 'ethereum' || c.symbol === 'eth');
  const bitcoinChange = bitcoin?.price_change_percentage_24h || 0;
  const ethereumChange = ethereum?.price_change_percentage_24h || 0;

  const trends: string[] = [];
  const summaryParts: string[] = [];

  if (bitcoin) {
    if (bitcoinChange > 2) {
      trends.push('Bitcoin showing strong momentum');
      summaryParts.push(
        `Bitcoin (BTC) is leading the market higher with a ${bitcoinChange.toFixed(1)}% gain`,
      );
    } else if (bitcoinChange > 0) {
      trends.push('Bitcoin in positive territory');
      summaryParts.push(
        `Bitcoin (BTC) is trading in positive territory with a ${bitcoinChange.toFixed(1)}% increase`,
      );
    } else if (bitcoinChange > -2) {
      trends.push('Bitcoin consolidating');
      summaryParts.push(
        `Bitcoin (BTC) is consolidating with a ${bitcoinChange.toFixed(1)}% change`,
      );
    } else {
      trends.push('Bitcoin under pressure');
      summaryParts.push(
        `Bitcoin (BTC) is facing selling pressure with a ${bitcoinChange.toFixed(1)}% decline`,
      );
    }
  }

  if (ethereum && Math.abs(ethereumChange) > 1) {
    if (ethereumChange > 0) {
      summaryParts.push(`while Ethereum (ETH) follows with a ${ethereumChange.toFixed(1)}% gain`);
    } else {
      summaryParts.push(`while Ethereum (ETH) declines by ${Math.abs(ethereumChange).toFixed(1)}%`);
    }
  }

  if (gainerRatio > 0.6) {
    trends.push('Broad market strength');
    summaryParts.push('The broader altcoin market shows increased momentum');
  } else if (gainerRatio < 0.4) {
    trends.push('Broad market weakness');
    summaryParts.push('with most altcoins experiencing declines');
  } else {
    trends.push('Mixed market conditions');
    summaryParts.push('with mixed signals across the altcoin market');
  }

  if (topMovers.gainers.length > 0) {
    const topGainers = topMovers.gainers.slice(0, 3);
    const gainerNames = topGainers.map((c) => c.name).join(', ');
    const topGainer = topGainers[0];
    const topGain = topGainer.price_change_percentage_24h || 0;

    trends.push(`${gainerNames} among top gainers`);
    summaryParts.push(
      `Leading the gainers is ${topGainer.name} (${topGainer.symbol.toUpperCase()}) with an impressive ${topGain.toFixed(1)}% surge`,
    );
    if (topGainers.length > 1) {
      summaryParts.push(
        `followed by ${topGainers
          .slice(1)
          .map((c) => `${c.name} (+${(c.price_change_percentage_24h || 0).toFixed(1)}%)`)
          .join(', ')}`,
      );
    }
  }

  if (topMovers.losers.length > 0) {
    const topLosers = topMovers.losers.slice(0, 3);
    const loserNames = topLosers.map((c) => c.name).join(', ');
    const topLoser = topLosers[0];
    const topLoss = topLoser.price_change_percentage_24h || 0;

    trends.push(`${loserNames} among top losers`);
    summaryParts.push(
      `On the downside, ${topLoser.name} (${topLoser.symbol.toUpperCase()}) leads the losers with a ${Math.abs(topLoss).toFixed(1)}% decline`,
    );
    if (topLosers.length > 1) {
      summaryParts.push(
        `alongside ${topLosers
          .slice(1)
          .map((c) => `${c.name} (${(c.price_change_percentage_24h || 0).toFixed(1)}%)`)
          .join(', ')}`,
      );
    }
  }

  if (volumeSpikes.length > 0) {
    const significantVolumeSpikes = volumeSpikes.slice(0, 3);
    const volumeNames = significantVolumeSpikes.map((c) => c.name).join(', ');
    const topVolumeCoin = significantVolumeSpikes[0];
    const volumeRatio = (topVolumeCoin.total_volume || 0) / (topVolumeCoin.market_cap || 1);

    trends.push(`Elevated trading activity in ${volumeNames}`);
    summaryParts.push(
      `Trading volume remains elevated, with ${topVolumeCoin.name} showing particularly high activity`,
    );
    if (volumeRatio > 0.2) {
      summaryParts.push(
        `indicating strong institutional or whale interest with volume-to-market-cap ratio of ${(volumeRatio * 100).toFixed(1)}%`,
      );
    }
  }

  if (nearHigh.length > 0) {
    const nearHighCoins = nearHigh.slice(0, 3);
    const nearHighNames = nearHighCoins.map((c) => c.name).join(', ');

    trends.push(`${nearHighNames} approaching 7-day highs`);
    summaryParts.push(
      `Several coins are approaching their 7-day highs, including ${nearHighNames}`,
    );
    summaryParts.push(
      `suggesting potential breakout opportunities or resistance levels being tested`,
    );
  }

  if (whaleSignals.length > 0) {
    const topWhaleSignals = whaleSignals.slice(0, 3);
    const whaleNames = topWhaleSignals.map((s) => s.coin.name).join(', ');
    const strongestSignal = topWhaleSignals[0];

    trends.push(`Potential accumulation signals in ${whaleNames}`);
    summaryParts.push(
      `Notable accumulation signals are detected, with ${strongestSignal.coin.name} showing the strongest signal strength of ${strongestSignal.signalStrength}%`,
    );
    if (topWhaleSignals.length > 1) {
      summaryParts.push(
        `Other coins showing accumulation patterns include ${topWhaleSignals
          .slice(1)
          .map((s) => s.coin.name)
          .join(', ')}`,
      );
    }
    summaryParts.push(
      `These patterns typically indicate large investors building positions, which could signal future price movements`,
    );
  }

  const totalVolume = coins.reduce((sum, coin) => sum + (coin.total_volume || 0), 0);
  const avgVolume = totalVolume / coins.length;
  const highVolumeCount = coins.filter((c) => (c.total_volume || 0) > avgVolume * 1.5).length;

  if (highVolumeCount > 10) {
    trends.push('Elevated trading activity across the market');
    summaryParts.push(
      `Overall market activity remains robust, with ${highVolumeCount} coins showing above-average trading volume`,
    );
  }

  const marketCapChange =
    coins.reduce((sum, coin) => sum + (coin.market_cap_change_percentage_24h || 0), 0) /
    coins.length;

  if (Math.abs(marketCapChange) > 1) {
    if (marketCapChange > 0) {
      summaryParts.push(
        `The total cryptocurrency market capitalization has increased by approximately ${marketCapChange.toFixed(1)}%`,
      );
    } else {
      summaryParts.push(
        `The total cryptocurrency market capitalization has decreased by approximately ${Math.abs(marketCapChange).toFixed(1)}%`,
      );
    }
  }

  let summary = summaryParts.join('. ') + '.';

  summary += ' All metrics reflect the last 24 hours of trading activity.';

  let sentiment: 'bullish' | 'bearish' | 'neutral' = 'neutral';
  const positiveFactors =
    (avgPriceChange > 0 ? 1 : 0) +
    (gainerRatio > 0.5 ? 1 : 0) +
    (bitcoinChange > 0 ? 1 : 0) +
    (topMovers.gainers.length > topMovers.losers.length ? 1 : 0) +
    (whaleSignals.length > 3 ? 1 : 0);

  const negativeFactors =
    (avgPriceChange < 0 ? 1 : 0) +
    (gainerRatio < 0.5 ? 1 : 0) +
    (bitcoinChange < -2 ? 1 : 0) +
    (topMovers.losers.length > topMovers.gainers.length ? 1 : 0);

  if (positiveFactors > negativeFactors + 1 && avgPriceChange > 1) {
    sentiment = 'bullish';
  } else if (negativeFactors > positiveFactors + 1 && avgPriceChange < -1) {
    sentiment = 'bearish';
  }

  return {
    summary,
    sentiment,
    keyTrends: trends.slice(0, 8),
  };
}
