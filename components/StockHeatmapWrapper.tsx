"use client";

import { useState } from "react";
import StockHeatmapWithWatchlist from "./StockHeatmapWithWatchlist";

interface StockHeatmapWrapperProps {
  scriptUrl: string;
  height?: number;
  className?: string;
  initialWatchlistSymbols?: string[];
}

const StockHeatmapWrapper: React.FC<StockHeatmapWrapperProps> = ({
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
    <StockHeatmapWithWatchlist
      scriptUrl={scriptUrl}
      height={height}
      className={className}
      watchlistSymbols={watchlistSymbols}
      onWatchlistUpdate={handleWatchlistUpdate}
    />
  );
};

export default StockHeatmapWrapper;
