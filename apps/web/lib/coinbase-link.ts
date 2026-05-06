import type { AssetType } from '@/lib/types';

export type CoinbaseLinkState = {
  available: boolean;
  href: string | null;
  label: string;
  reason: string | null;
};

const COINBASE_ORIGIN = 'https://www.coinbase.com';

const CRYPTO_SLUGS: Record<string, string> = {
  AAVE: 'aave',
  ADA: 'cardano',
  AVAX: 'avalanche',
  BCH: 'bitcoin-cash',
  BTC: 'bitcoin',
  DOGE: 'dogecoin',
  DOT: 'polkadot',
  ETH: 'ethereum',
  FIL: 'filecoin',
  GRT: 'the-graph',
  LINK: 'chainlink',
  LTC: 'litecoin',
  MATIC: 'polygon',
  POL: 'polygon-ecosystem-token',
  SHIB: 'shiba-inu',
  SOL: 'solana',
  UNI: 'uniswap',
  XRP: 'xrp',
};

function cleanSymbol(ticker: string): string | null {
  const cleaned = ticker.trim().toUpperCase().replace(/\/USD$/, '').replace(/[-_ ]USD$/, '');
  if (!cleaned || !/^[A-Z0-9.:-]{1,20}$/.test(cleaned)) {
    return null;
  }
  return cleaned;
}

function safeCoinbaseUrl(path: string, query?: Record<string, string>): string | null {
  const url = new URL(path, COINBASE_ORIGIN);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    url.searchParams.set(key, value);
  });
  return url.origin === COINBASE_ORIGIN ? url.toString() : null;
}

export function buildCoinbaseLink(ticker: string, assetType: AssetType): CoinbaseLinkState {
  const symbol = cleanSymbol(ticker);
  if (!symbol) {
    return {
      available: false,
      href: null,
      label: 'Open Coinbase search',
      reason: 'Coinbase link unavailable for an invalid ticker.',
    };
  }

  if (assetType === 'crypto') {
    const slug = CRYPTO_SLUGS[symbol];
    if (slug) {
      const href = safeCoinbaseUrl(`/price/${slug}`);
      return {
        available: Boolean(href),
        href,
        label: 'Open on Coinbase',
        reason: href ? null : 'Coinbase link could not be built safely.',
      };
    }
  }

  const href = safeCoinbaseUrl('/explore', { q: symbol });
  return {
    available: Boolean(href),
    href,
    label: 'Open Coinbase search',
    reason: href ? null : 'Coinbase search link could not be built safely.',
  };
}
