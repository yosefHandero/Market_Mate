/**
 * @vitest-environment jsdom
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { DecisionGrid } from '@/components/decision-grid';
import { getDashboardFixture } from '@/tests/fixtures/dashboard-fixture';
import type { ScanResult } from '@/lib/types';

vi.mock('@/components/decision-card', () => ({
  DecisionCard: ({ result }: { result: { ticker: string } }) => (
    <div data-testid={`card-${result.ticker}`}>{result.ticker}</div>
  ),
}));

describe('DecisionGrid', () => {
  it('renders stock and crypto buy-candidate sections', () => {
    const fixture = getDashboardFixture();
    render(
      <DecisionGrid
        results={fixture.latestScan.results}
        topStocks={fixture.latestScan.top_stocks}
        topCrypto={fixture.latestScan.top_crypto}
        decisions={fixture.decisions}
        automation={fixture.automation}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Top Stock Buy Candidates' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Top Crypto Buy Candidates' })).toBeInTheDocument();
    expect(screen.getByTestId('card-NVDA')).toBeInTheDocument();
    expect(screen.getByTestId('card-BTC/USD')).toBeInTheDocument();
  });

  it('never surfaces HOLD or SELL candidates on the buy-candidate grid', () => {
    const fixture = getDashboardFixture();
    const bullishHold = {
      ticker: 'ADA/USD',
      asset_type: 'crypto',
      decision_signal: 'HOLD',
      is_buy_candidate: true,
      weekly_prediction: { directional_bias: 'bullish' },
      provider_status: 'ok',
      bar_age_minutes: 3,
      freshness_flags: {},
      readiness_hard_stop: false,
    } as unknown as ScanResult;
    render(
      <DecisionGrid
        results={[...fixture.latestScan.results, bullishHold]}
        topStocks={fixture.latestScan.top_stocks}
        topCrypto={[...(fixture.latestScan.top_crypto ?? []), bullishHold]}
        decisions={fixture.decisions}
        automation={fixture.automation}
      />,
    );

    // DOGE/USD is a HOLD in the fixture top picks and must be filtered out.
    expect(screen.queryByTestId('card-DOGE/USD')).not.toBeInTheDocument();
    expect(screen.queryByTestId('card-ADA/USD')).not.toBeInTheDocument();
  });

  it('explains the exact reason when nothing was scanned', () => {
    render(<DecisionGrid results={[]} decisions={[]} automation={null} />);
    expect(screen.getByTestId('stock-empty-state')).toHaveTextContent(
      /no stock symbols were scanned/i,
    );
    expect(screen.getByTestId('crypto-empty-state')).toHaveTextContent(
      /no crypto symbols were scanned/i,
    );
  });

  it('shows held-back buy candidates as read-only reference during closed markets', () => {
    const heldBack = {
      ticker: 'AAPL',
      asset_type: 'stock',
      decision_signal: 'BUY',
      provider_status: 'critical',
      bar_age_minutes: 1120,
      freshness_flags: { market_bars: 'stale' },
      readiness_hard_stop: true,
      readiness_reason: 'Hard stop: provider is critical and bars are stale over 6 hours.',
    } as unknown as import('@/lib/types').ScanResult;

    render(<DecisionGrid results={[heldBack]} decisions={[]} automation={null} />);
    // No executable empty-state; instead a clearly-labeled read-only reference section.
    expect(screen.queryByTestId('stock-empty-state')).not.toBeInTheDocument();
    expect(screen.getByTestId('stock-reference-note')).toHaveTextContent(
      /reference only - not executable right now\. 1 stock buy candidate held back: provider is critical and bars are stale/i,
    );
    expect(screen.getByTestId('stock-reference-grid')).toBeInTheDocument();
    expect(screen.getByTestId('card-AAPL')).toBeInTheDocument();
  });

  it('splits blocked top BUY setups into a read-only section when valid candidates remain', () => {
    const valid = {
      ticker: 'NVDA',
      asset_type: 'stock',
      decision_signal: 'BUY',
      is_buy_candidate: true,
      provider_status: 'ok',
      bar_age_minutes: 3,
      freshness_flags: {},
      readiness_hard_stop: false,
      readiness_score: 85,
      readiness_band: 'high',
      readiness_reason: 'Actionable: gates passed and data is fresh.',
      gate_passed: true,
      recommended_action: 'preview',
    } as unknown as ScanResult;
    const blocked = {
      ...valid,
      ticker: 'ROKU',
      provider_status: 'critical',
      bar_age_minutes: 420,
      freshness_flags: { bars: 'stale' },
      readiness_hard_stop: true,
      readiness_reason: 'Hard stop: provider is critical and bars are stale over 6 hours.',
      execution_eligibility: 'blocked',
    } as unknown as ScanResult;

    render(
      <DecisionGrid
        results={[valid, blocked]}
        topStocks={[valid, blocked]}
        decisions={[]}
        automation={null}
      />,
    );

    expect(
      within(screen.getByTestId('stock-actionable-grid')).getByTestId('card-NVDA'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('stock-actionable-grid')).queryByTestId('card-ROKU'),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('stock-readonly-note')).toHaveTextContent(/read-only setup details/i);
    expect(
      within(screen.getByTestId('stock-readonly-grid')).getByTestId('card-ROKU'),
    ).toBeInTheDocument();
  });

  it('does not expose shadow rows on the Decision surface', () => {
    const production = {
      ticker: 'NVDA',
      asset_type: 'stock',
      decision_signal: 'BUY',
      is_buy_candidate: true,
      provider_status: 'ok',
      bar_age_minutes: 3,
      freshness_flags: {},
      readiness_hard_stop: false,
      readiness_score: 85,
      readiness_band: 'high',
      readiness_reason: 'Actionable: gates passed and data is fresh.',
      gate_passed: true,
      recommended_action: 'preview',
      decision_role: 'production',
    } as unknown as ScanResult;
    const shadow = {
      ...production,
      ticker: 'WEEKLY-SHADOW',
      decision_role: 'shadow',
    } as unknown as ScanResult;

    render(
      <DecisionGrid
        results={[production, shadow]}
        topStocks={[production, shadow]}
        decisions={[]}
        automation={null}
      />,
    );

    expect(screen.getByTestId('card-NVDA')).toBeInTheDocument();
    expect(screen.queryByTestId('card-WEEKLY-SHADOW')).not.toBeInTheDocument();
  });

  it('explains when nothing meets the buy threshold', () => {
    const holds = ['A', 'B', 'C'].map(
      (ticker) =>
        ({
          ticker,
          asset_type: 'crypto',
          decision_signal: 'HOLD',
          provider_status: 'ok',
          bar_age_minutes: 3,
          freshness_flags: { market_bars: 'ok' },
          readiness_hard_stop: false,
        }) as unknown as import('@/lib/types').ScanResult,
    );

    render(<DecisionGrid results={holds} decisions={[]} automation={null} />);
    expect(screen.getByTestId('crypto-empty-state')).toHaveTextContent(
      /No crypto buy candidates qualified from 3 crypto symbols\. Likely blockers: no qualifying BUY signal was present\./i,
    );
  });

  it('explains sparse stock and crypto sections independently', () => {
    const stockCandidate = {
      ticker: 'MSFT',
      asset_type: 'stock',
      decision_signal: 'BUY',
      is_buy_candidate: true,
      provider_status: 'ok',
      bar_age_minutes: 3,
      freshness_flags: {},
      readiness_hard_stop: false,
      readiness_score: 85,
      readiness_band: 'high',
      readiness_reason: 'Actionable: gates passed and data is fresh.',
      gate_passed: true,
      recommended_action: 'preview',
    } as unknown as ScanResult;
    const rejectedStock = {
      ...stockCandidate,
      ticker: 'INTC',
      is_buy_candidate: false,
      confidence_score: 42,
    } as unknown as ScanResult;
    const cryptoCandidate = {
      ...stockCandidate,
      ticker: 'ETH/USD',
      asset_type: 'crypto',
    } as unknown as ScanResult;
    const staleCrypto = {
      ...cryptoCandidate,
      ticker: 'AVAX/USD',
      is_buy_candidate: false,
      bar_age_minutes: 1200,
      freshness_flags: { market_bars: 'stale' },
    } as unknown as ScanResult;

    render(
      <DecisionGrid
        results={[stockCandidate, rejectedStock, cryptoCandidate, staleCrypto]}
        topStocks={[stockCandidate]}
        topCrypto={[cryptoCandidate]}
        decisions={[]}
        automation={null}
      />,
    );

    expect(screen.getByTestId('stock-sparse-state')).toHaveTextContent(
      /Only 1 stock buy candidate qualified from 2 stock symbols\. Likely blockers:/i,
    );
    expect(screen.getByTestId('crypto-sparse-state')).toHaveTextContent(
      /Only 1 crypto buy candidate qualified from 2 crypto symbols\. Likely blockers:/i,
    );
  });
});
