"use client";

import { useState } from "react";
import MarketOverviewWithWatchlist from "./MarketOverviewWithWatchlist";

interface MarketOverviewWrapperProps {
  scriptUrl: string;
  height?: number;
  className?: string;
  initialWatchlistSymbols?: string[];
}

const MarketOverviewWrapper: React.FC<MarketOverviewWrapperProps> = ({
  scriptUrl,
  height = 600,
  className,
  initialWatchlistSymbols = [],
}) => {
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>(
    initialWatchlistSymbols
  );

  const handleWatchlistUpdate = async () => {
    // Fetch updated watchlist
    try {
      const response = await fetch("/api/watchlist");
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.data) {
          setWatchlistSymbols(
            data.data.map((item: { symbol: string }) =>
              item.symbol.toUpperCase()
            )
          );
        }
      }
    } catch (error) {
      console.error("Failed to fetch watchlist:", error);
    }
  };

  return (
    <MarketOverviewWithWatchlist
      scriptUrl={scriptUrl}
      height={height}
      className={className}
      watchlistSymbols={watchlistSymbols}
      onWatchlistUpdate={handleWatchlistUpdate}
    />
  );
};

export default MarketOverviewWrapper;
