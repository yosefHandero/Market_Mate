import { clsx, type ClassValue } from 'clsx';
import { Time } from 'lightweight-charts';
import { twMerge } from 'tailwind-merge';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Memoized formatCurrency with cache
const currencyCache = new Map<string, string>();

export function formatCurrency(
  value: number | null | undefined,
  digits?: number,
  currency?: string,
  showSymbol?: boolean,
) {
  if (value === null || value === undefined || isNaN(value)) {
    return showSymbol !== false ? '$0.00' : '0.00';
  }

  const cacheKey = `${value}-${digits ?? 'default'}-${currency ?? 'USD'}-${showSymbol ?? 'default'}`;
  const cached = currencyCache.get(cacheKey);
  if (cached !== undefined) {
    return cached;
  }

  let formatted: string;
  if (showSymbol === undefined || showSymbol === true) {
    formatted = value.toLocaleString(undefined, {
      style: 'currency',
      currency: currency?.toUpperCase() || 'USD',
      minimumFractionDigits: digits ?? 2,
      maximumFractionDigits: digits ?? 2,
    });
  } else {
    formatted = value.toLocaleString(undefined, {
      minimumFractionDigits: digits ?? 2,
      maximumFractionDigits: digits ?? 2,
    });
  }

  // Limit cache size to prevent memory leaks
  if (currencyCache.size > 1000) {
    const firstKey = currencyCache.keys().next().value;
    currencyCache.delete(firstKey);
  }
  currencyCache.set(cacheKey, formatted);
  return formatted;
}

export function formatPercentage(change: number | null | undefined): string {
  if (change === null || change === undefined || isNaN(change)) {
    return '0.0%';
  }
  const formattedChange = change.toFixed(1);
  return `${formattedChange}%`;
}

// Enhanced trend utilities
export type TrendDirection = 'up' | 'down' | 'neutral';

export interface TrendInfo {
  direction: TrendDirection;
  textClass: string;
  bgClass: string;
  icon: typeof TrendingUp | typeof TrendingDown | typeof Minus;
  color: string;
}

/**
 * Get comprehensive trend information from a numeric value
 * @param value - The numeric value (positive = up, negative = down, zero = neutral)
 * @returns Trend information including classes, icon, and color
 */
export function getTrendInfo(value: number | null | undefined): TrendInfo {
  if (value === null || value === undefined || isNaN(value)) {
    return {
      direction: 'neutral',
      textClass: 'text-gray-400',
      bgClass: 'bg-gray-500/10',
      icon: Minus,
      color: '#9ca3af',
    };
  }

  const isTrendingUp = value > 0;
  const isNeutral = value === 0;

  if (isNeutral) {
    return {
      direction: 'neutral',
      textClass: 'text-gray-400',
      bgClass: 'bg-gray-500/10',
      icon: Minus,
      color: '#9ca3af',
    };
  }

  if (isTrendingUp) {
    return {
      direction: 'up',
      textClass: 'text-green-400',
      bgClass: 'bg-green-500/10',
      icon: TrendingUp,
      color: '#4ade80',
    };
  }

  return {
    direction: 'down',
    textClass: 'text-red-400',
    bgClass: 'bg-red-500/10',
    icon: TrendingDown,
    color: '#f87171',
  };
}

/**
 * Get trend color (hex) from value
 */
export function getTrendColor(value: number | null | undefined): string {
  return getTrendInfo(value).color;
}

/**
 * Get trend icon component from value
 */
export function getTrendIcon(value: number | null | undefined) {
  return getTrendInfo(value).icon;
}

// Legacy function for backward compatibility
export function trendingClasses(value: number) {
  const trend = getTrendInfo(value);
  return {
    textClass: trend.textClass,
    bgClass: trend.bgClass,
    iconClass: trend.direction === 'up' ? 'icon-up' : 'icon-down',
  };
}

export function timeAgo(date: string | number | Date): string {
  const now = new Date();
  const past = new Date(date);
  const diff = now.getTime() - past.getTime(); // difference in ms

  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const weeks = Math.floor(days / 7);

  if (seconds < 60) return 'just now';
  if (minutes < 60) return `${minutes} min`;
  if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''}`;
  if (days < 7) return `${days} day${days > 1 ? 's' : ''}`;
  if (weeks < 4) return `${weeks} week${weeks > 1 ? 's' : ''}`;

  // Format date as YYYY-MM-DD
  return past.toISOString().split('T')[0];
}

export function convertOHLCData(data: OHLCData[]) {
  return data
    .map((d) => ({
      time: d[0] as Time, // ensure seconds, not ms
      open: d[1],
      high: d[2],
      low: d[3],
      close: d[4],
    }))
    .filter((item, index, arr) => index === 0 || item.time !== arr[index - 1].time);
}

export const ELLIPSIS = 'ellipsis' as const;
export const buildPageNumbers = (
  currentPage: number,
  totalPages: number,
): (number | typeof ELLIPSIS)[] => {
  const MAX_VISIBLE_PAGES = 5;

  const pages: (number | typeof ELLIPSIS)[] = [];

  if (totalPages <= MAX_VISIBLE_PAGES) {
    for (let i = 1; i <= totalPages; i += 1) {
      pages.push(i);
    }
    return pages;
  }

  pages.push(1);

  const start = Math.max(2, currentPage - 1);
  const end = Math.min(totalPages - 1, currentPage + 1);

  if (start > 2) {
    pages.push(ELLIPSIS);
  }

  for (let i = start; i <= end; i += 1) {
    pages.push(i);
  }

  if (end < totalPages - 1) {
    pages.push(ELLIPSIS);
  }

  pages.push(totalPages);

  return pages;
};
