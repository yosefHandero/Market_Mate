'use client';

import { useEffect, useState } from 'react';
import { fetcher } from '@/lib/coingecko.actions';
import { CoinMarketData } from '@/type';

/**
 * Shared hook for fetching market data
 * Used across multiple pages for consistent data fetching
 */
export function useMarketData() {
  const [coins, setCoins] = useState<CoinMarketData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const data = await fetcher<CoinMarketData[]>('/coins/markets', {
          vs_currency: 'usd',
          order: 'market_cap_desc',
          per_page: 100,
          page: 1,
          sparkline: 'false',
          price_change_percentage: '24h',
        });
        setCoins(data || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load market data');
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  return { coins, loading, error };
}

