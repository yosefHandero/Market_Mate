'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { fetcher } from '@/lib/coingecko.actions';
import { CoinMarketData } from '@/type';

interface UseMarketDataOptions {
  vsCurrency?: string;
  order?: string;
  perPage?: number;
  page?: number;
  revalidate?: number;
}

interface UseMarketDataReturn {
  data: CoinMarketData[];
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
  totalMarketCap: number;
  averagePriceChange: number;
  gainersCount: number;
  losersCount: number;
}

export function useMarketData(options: UseMarketDataOptions = {}): UseMarketDataReturn {
  const {
    vsCurrency = 'usd',
    order = 'market_cap_desc',
    perPage = 100,
    page = 1,
    revalidate = 60,
  } = options;

  const [data, setData] = useState<CoinMarketData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await fetcher<CoinMarketData[]>('/coins/markets', {
        vs_currency: vsCurrency,
        order,
        per_page: perPage,
        page,
        sparkline: 'false',
        price_change_percentage: '24h',
      });

      setData(result || []);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch market data'));
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [vsCurrency, order, perPage, page]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totalMarketCap = useMemo(
    () => data.reduce((sum, coin) => sum + (coin.market_cap || 0), 0),
    [data],
  );

  const averagePriceChange = useMemo(() => {
    if (data.length === 0) return 0;
    const sum = data.reduce((acc, coin) => acc + (coin.price_change_percentage_24h || 0), 0);
    return sum / data.length;
  }, [data]);

  const gainersCount = useMemo(
    () => data.filter((coin) => (coin.price_change_percentage_24h || 0) > 0).length,
    [data],
  );

  const losersCount = useMemo(
    () => data.filter((coin) => (coin.price_change_percentage_24h || 0) < 0).length,
    [data],
  );

  return {
    data,
    loading,
    error,
    refetch: fetchData,
    totalMarketCap,
    averagePriceChange,
    gainersCount,
    losersCount,
  };
}
