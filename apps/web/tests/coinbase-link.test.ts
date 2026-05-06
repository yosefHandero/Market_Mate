import { describe, expect, it } from 'vitest';
import { buildCoinbaseLink } from '@/lib/coinbase-link';

describe('buildCoinbaseLink', () => {
  it('builds direct Coinbase price links for known crypto symbols', () => {
    expect(buildCoinbaseLink('BTC/USD', 'crypto')).toEqual({
      available: true,
      href: 'https://www.coinbase.com/price/bitcoin',
      label: 'Open on Coinbase',
      reason: null,
    });
    expect(buildCoinbaseLink('eth', 'crypto').href).toBe(
      'https://www.coinbase.com/price/ethereum',
    );
  });

  it('falls back to Coinbase search for unknown crypto', () => {
    const link = buildCoinbaseLink('BONK/USD', 'crypto');
    expect(link.available).toBe(true);
    expect(link.href).toBe('https://www.coinbase.com/explore?q=BONK');
  });

  it('uses conservative Coinbase search for stocks', () => {
    const link = buildCoinbaseLink('AAPL', 'stock');
    expect(link.available).toBe(true);
    expect(link.href).toBe('https://www.coinbase.com/explore?q=AAPL');
  });

  it('rejects invalid tickers', () => {
    const link = buildCoinbaseLink('', 'stock');
    expect(link.available).toBe(false);
    expect(link.href).toBeNull();
  });

  it('only emits Coinbase origins', () => {
    const links = [
      buildCoinbaseLink('SOL', 'crypto'),
      buildCoinbaseLink('TSLA', 'stock'),
      buildCoinbaseLink('ETH/USD', 'crypto'),
    ];
    expect(links.every((link) => link.href && new URL(link.href).origin === 'https://www.coinbase.com')).toBe(
      true,
    );
  });
});
