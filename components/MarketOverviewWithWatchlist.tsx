"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import TradingViewWidget from "@/components/TradingViewWidget";
import StockActionDialog from "@/components/StockActionDialog";
import WatchlistButton from "@/components/WatchlistButton";
import { MARKET_OVERVIEW_WIDGET_CONFIG } from "@/lib/constants";

interface MarketOverviewWithWatchlistProps {
  scriptUrl: string;
  height?: number;
  className?: string;
  watchlistSymbols?: string[];
  onWatchlistUpdate?: () => void;
}

const MarketOverviewWithWatchlist: React.FC<
  MarketOverviewWithWatchlistProps
> = ({
  scriptUrl,
  height = 600,
  className,
  watchlistSymbols = [],
  onWatchlistUpdate,
}) => {
  const [hoveredSymbol, setHoveredSymbol] = useState<string | null>(null);
  const [hoverPosition, setHoverPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [isHovering, setIsHovering] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [clickedSymbol, setClickedSymbol] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetContainerRef = useRef<HTMLDivElement>(null);
  const lastClickSymbolRef = useRef<string | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Extract symbol from TradingView format (e.g., "NYSE:JPM" -> "JPM")
  const extractSymbol = useCallback(
    (symbolStr: string | null): string | null => {
      if (!symbolStr) return null;
      const parts = symbolStr.split(":");
      return parts.length > 1
        ? parts[1].toUpperCase()
        : symbolStr.toUpperCase();
    },
    []
  );

  // Enhanced config - remove symbolUrl to prevent navigation if it exists
  // We'll capture symbols via hover detection and postMessage instead
  const enhancedConfig = { ...MARKET_OVERVIEW_WIDGET_CONFIG };
  if ("symbolUrl" in enhancedConfig) {
    delete (enhancedConfig as { symbolUrl?: string }).symbolUrl;
  }

  // Listen for postMessage events from TradingView widget
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // TradingView widgets may send postMessage events with symbol info
      if (event.data && typeof event.data === "object") {
        // Check various possible message formats
        if ("symbol" in event.data) {
          const symbol = extractSymbol(event.data.symbol as string);
          if (symbol) {
            lastClickSymbolRef.current = symbol;
            setSelectedSymbol(symbol);
            setHoveredSymbol(symbol);
            setIsHovering(true);
          }
        } else if (
          "name" in event.data &&
          typeof event.data.name === "string"
        ) {
          // Some widgets send 'name' field
          const symbol = extractSymbol(event.data.name);
          if (symbol) {
            lastClickSymbolRef.current = symbol;
            setSelectedSymbol(symbol);
            setHoveredSymbol(symbol);
            setIsHovering(true);
          }
        }
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [extractSymbol]);

  // Handle mouse move to track position
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      setHoverPosition({ x, y });

      // If we have a hovered symbol, show the overlay
      if (hoveredSymbol) {
        setIsHovering(true);
        // Clear any existing timeout
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
        }
      }
    },
    [hoveredSymbol]
  );

  // Handle mouse leave to hide overlay
  const handleMouseLeave = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      setIsHovering(false);
      setHoveredSymbol(null);
      setHoverPosition(null);
    }, 200);
  }, []);

  // Handle touch events for mobile
  const handleTouchStart = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      if (!containerRef.current) return;

      const touch = e.touches[0];
      const rect = containerRef.current.getBoundingClientRect();
      const x = touch.clientX - rect.left;
      const y = touch.clientY - rect.top;

      setHoverPosition({ x, y });

      // Use lastClickSymbolRef if available
      const symbolToUse = lastClickSymbolRef.current || selectedSymbol;
      if (symbolToUse) {
        setHoveredSymbol(symbolToUse);
        setIsHovering(true);
      }
    },
    [selectedSymbol]
  );

  const handleTouchEnd = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      setIsHovering(false);
      setHoveredSymbol(null);
      setHoverPosition(null);
    }, 2000);
  }, []);

  // Handle click to open dialog
  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const y = e.clientY - rect.top;

      // Market Overview has stock items in the lower section (below chart)
      // If clicking in the lower 60% of widget, it's likely on a stock item
      const isInStockArea = y > rect.height * 0.4;

      // Use lastClickSymbolRef if available (from TradingView widget click)
      const symbolToUse = lastClickSymbolRef.current || hoveredSymbol;

      if (isInStockArea && symbolToUse) {
        setClickedSymbol(symbolToUse);
        setDialogOpen(true);
      }
    },
    [hoveredSymbol]
  );

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const hoveredSymbolInWatchlist = hoveredSymbol
    ? watchlistSymbols.includes(hoveredSymbol.toUpperCase())
    : false;

  const clickedSymbolInWatchlist = clickedSymbol
    ? watchlistSymbols.includes(clickedSymbol.toUpperCase())
    : false;

  return (
    <div className="relative w-full">
      <div ref={widgetContainerRef}>
        <TradingViewWidget
          title="Market Overview"
          scriptUrl={scriptUrl}
          config={enhancedConfig}
          className={className}
          height={height}
        />
      </div>
      <div
        ref={containerRef}
        className="absolute inset-0 pointer-events-auto"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        onClick={handleClick}
        style={{ zIndex: 10 }}
      />
      {/* Hover overlay with watchlist button */}
      {isHovering && hoveredSymbol && hoverPosition && (
        <div
          className="watchlist-overlay-button"
          style={{
            position: "absolute",
            left: `${hoverPosition.x}px`,
            top: `${hoverPosition.y}px`,
            transform: "translate(-50%, -100%)",
            marginTop: "-8px",
            zIndex: 20,
            pointerEvents: "auto",
          }}
          onMouseEnter={() => {
            if (timeoutRef.current) {
              clearTimeout(timeoutRef.current);
            }
          }}
          onMouseLeave={handleMouseLeave}
        >
          <WatchlistButton
            symbol={hoveredSymbol}
            company={hoveredSymbol}
            isInWatchlist={hoveredSymbolInWatchlist}
            type="icon"
            onWatchlistChange={(_symbol, _isAdded) => {
              if (onWatchlistUpdate) {
                onWatchlistUpdate();
              }
              // Keep overlay visible after action
              setIsHovering(true);
            }}
          />
        </div>
      )}
      {clickedSymbol && (
        <StockActionDialog
          open={dialogOpen}
          onOpenChange={(open) => {
            setDialogOpen(open);
            if (!open) {
              // Clear clicked symbol when dialog closes
              setTimeout(() => setClickedSymbol(null), 200);
            }
          }}
          symbol={clickedSymbol}
          company={clickedSymbol}
          isInWatchlist={clickedSymbolInWatchlist}
          onWatchlistChange={(_symbol, _isAdded) => {
            if (onWatchlistUpdate) {
              onWatchlistUpdate();
            }
          }}
        />
      )}
    </div>
  );
};

export default MarketOverviewWithWatchlist;
