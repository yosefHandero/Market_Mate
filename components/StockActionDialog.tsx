"use client";

import React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import WatchlistButton from "@/components/WatchlistButton";
import { ExternalLink } from "lucide-react";

interface StockActionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  symbol: string;
  company?: string;
  isInWatchlist: boolean;
  onWatchlistChange?: (symbol: string, isAdded: boolean) => void;
}

const StockActionDialog: React.FC<StockActionDialogProps> = ({
  open,
  onOpenChange,
  symbol,
  company,
  isInWatchlist,
  onWatchlistChange,
}) => {
  // Generate TradingView URL
  // TradingView URLs typically use format: https://www.tradingview.com/symbols/EXCHANGE:SYMBOL/
  // For now, we use a generic format that TradingView will resolve
  const getTradingViewUrl = (sym: string): string => {
    const upperSymbol = sym.toUpperCase();
    return `https://www.tradingview.com/symbols/${upperSymbol}/`;
  };

  const tradingViewUrl = getTradingViewUrl(symbol);

  const handleTradingViewClick = () => {
    window.open(tradingViewUrl, "_blank", "noopener,noreferrer");
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{symbol}</DialogTitle>
          {company && company !== symbol && (
            <DialogDescription>{company}</DialogDescription>
          )}
        </DialogHeader>
        <div className="flex flex-col gap-3 py-4">
          <button
            onClick={handleTradingViewClick}
            className="flex items-center justify-center gap-2 rounded-md border border-gray-700 bg-gray-800 px-4 py-3 text-sm font-medium text-white transition-colors focus:outline-none focus:ring-2 focus:ring-gray-600 focus:ring-offset-2 focus:ring-offset-gray-900"
          >
            <ExternalLink className="h-4 w-4" />
            <span>Open in TradingView</span>
          </button>
          <div className="flex items-center justify-center">
            <WatchlistButton
              symbol={symbol}
              company={company || symbol}
              isInWatchlist={isInWatchlist}
              type="button"
              onWatchlistChange={(sym, isAdded) => {
                onWatchlistChange?.(sym, isAdded);
                // Close dialog after adding/removing from watchlist
                setTimeout(() => {
                  onOpenChange(false);
                }, 500);
              }}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default StockActionDialog;
