"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import TradingViewWidget from "@/components/TradingViewWidget";
import StockActionDialog from "@/components/StockActionDialog";
import WatchlistButton from "@/components/WatchlistButton";
import { HEATMAP_WIDGET_CONFIG } from "@/lib/constants";

interface StockHeatmapWithWatchlistProps {
  scriptUrl: string;
  height?: number;
  className?: string;
  watchlistSymbols?: string[];
  onWatchlistUpdate?: () => void;
}

const StockHeatmapWithWatchlist: React.FC<StockHeatmapWithWatchlistProps> = ({
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

  // Extract symbol from TradingView format
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

  // Enhanced config - remove symbolUrl to prevent navigation
  // We'll capture symbols via hover detection and postMessage instead
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { symbolUrl: _symbolUrl, ...enhancedConfig } = HEATMAP_WIDGET_CONFIG;

  // Listen for postMessage events from TradingView widget
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // TradingView widgets may send postMessage events with symbol info
      if (event.data && typeof event.data === "object") {
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
    (_e: React.MouseEvent<HTMLDivElement>) => {
      // Use lastClickSymbolRef if available (from TradingView widget click)
      const symbolToUse = lastClickSymbolRef.current || hoveredSymbol;

      if (symbolToUse) {
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
          title="Stock Heatmap"
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

export default StockHeatmapWithWatchlist;
