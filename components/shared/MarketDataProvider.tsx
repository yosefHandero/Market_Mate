'use client';

import { createContext, useContext, ReactNode } from 'react';
import { useMarketData } from './useMarketData';
import { CoinMarketData } from '@/type';

interface MarketDataContextType {
  coins: CoinMarketData[];
  loading: boolean;
  error: string | null;
}

const MarketDataContext = createContext<MarketDataContextType | undefined>(undefined);

export function MarketDataProvider({ children }: { children: ReactNode }) {
  const marketData = useMarketData();

  return <MarketDataContext.Provider value={marketData}>{children}</MarketDataContext.Provider>;
}

export function useMarketDataContext() {
  const context = useContext(MarketDataContext);
  if (context === undefined) {
    throw new Error('useMarketDataContext must be used within a MarketDataProvider');
  }
  return context;
}
