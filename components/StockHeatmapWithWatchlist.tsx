"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import TradingViewWidget from "@/components/TradingViewWidget";
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
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [isHovering, setIsHovering] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetContainerRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastClickSymbolRef = useRef<string | null>(null);

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
  const { symbolUrl, ...enhancedConfig } = HEATMAP_WIDGET_CONFIG;

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
          }
        }
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [extractSymbol]);

  // Handle mouse move to detect hover over heatmap tiles
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // For heatmap, the entire area contains stock tiles
    setIsHovering(true);
    setHoverPosition({ x, y });

    // If we have a last clicked symbol, use it
    if (lastClickSymbolRef.current) {
      setHoveredSymbol(lastClickSymbolRef.current);
    }

    // Clear existing timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsHovering(false);
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      setHoverPosition(null);
      if (!selectedSymbol) {
        setHoveredSymbol(null);
      }
    }, 300);
  }, [selectedSymbol]);

  // Handle touch for mobile
  const handleTouchStart = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      if (!containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const touch = e.touches[0];
      const x = touch.clientX - rect.left;
      const y = touch.clientY - rect.top;

      setHoverPosition({ x, y });
      if (lastClickSymbolRef.current) {
        setHoveredSymbol(lastClickSymbolRef.current);
      }
    },
    []
  );

  const handleTouchEnd = useCallback(() => {
    // Keep button visible on mobile after touch
    setTimeout(() => {
      if (!isHovering && !selectedSymbol) {
        setHoverPosition(null);
        setHoveredSymbol(null);
      }
    }, 2000);
  }, [isHovering, selectedSymbol]);

  // Update hovered symbol when selected symbol changes
  useEffect(() => {
    if (selectedSymbol) {
      setHoveredSymbol(selectedSymbol);
    }
  }, [selectedSymbol]);

  // Listen for messages from TradingView widget (if it sends symbol info)
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // TradingView widgets may send postMessage events
      if (event.data && typeof event.data === "object") {
        if ("symbol" in event.data) {
          const symbol = extractSymbol(event.data.symbol as string);
          if (symbol) {
            lastClickSymbolRef.current = symbol;
            setSelectedSymbol(symbol);
            setHoveredSymbol(symbol);
          }
        }
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [extractSymbol]);

  const isInWatchlist = hoveredSymbol
    ? watchlistSymbols.includes(hoveredSymbol.toUpperCase())
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
        className="absolute inset-0 pointer-events-none"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        style={{ zIndex: 10 }}
      >
        {hoverPosition && hoveredSymbol && hoveredSymbol.length > 0 && (
          <div
            className="absolute pointer-events-auto z-20 animate-in fade-in-0 zoom-in-95 duration-200"
            style={{
              left: `${Math.min(
                hoverPosition.x + 10,
                (containerRef.current?.offsetWidth || window.innerWidth) - 220
              )}px`,
              top: `${Math.max(hoverPosition.y - 60, 10)}px`,
            }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="watchlist-overlay-button">
              <WatchlistButton
                symbol={hoveredSymbol}
                company={hoveredSymbol}
                isInWatchlist={isInWatchlist}
                type="button"
                onWatchlistChange={(symbol, isAdded) => {
                  if (onWatchlistUpdate) {
                    onWatchlistUpdate();
                  }
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default StockHeatmapWithWatchlist;
