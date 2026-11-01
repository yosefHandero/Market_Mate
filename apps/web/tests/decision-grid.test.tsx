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

    expect(screen.getByRole('heading', { name: 'Stocks' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Crypto' })).toBeInTheDocument();
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

  it('shows a short empty state with a Proof link when nothing was scanned', () => {
    render(<DecisionGrid results={[]} decisions={[]} automation={null} />);
    expect(screen.getByTestId('decision-empty-state')).toHaveTextContent(/no scan results yet/i);
    expect(screen.getByTestId('decision-proof-link')).toHaveAttribute('href', '/proof');
    expect(screen.queryByTestId('stock-empty-state')).not.toBeInTheDocument();
    expect(screen.queryByTestId('crypto-empty-state')).not.toBeInTheDocument();
  });

  it('keeps held-back buy candidates off the buy list during closed markets', () => {
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
    expect(screen.queryByTestId('card-AAPL')).not.toBeInTheDocument();
    expect(screen.queryByTestId('stock-reference-grid')).not.toBeInTheDocument();
    expect(screen.getByTestId('decision-empty-state')).toHaveTextContent(
      /no qualifying buy candidates/i,
    );
    expect(screen.getByTestId('decision-proof-link')).toHaveAttribute('href', '/proof');
    expect(screen.getByTestId('decision-data-warning')).toHaveTextContent(
      /stale or incomplete data is affecting these results/i,
    );
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
    expect(screen.queryByTestId('card-ROKU')).not.toBeInTheDocument();
    expect(screen.queryByTestId('stock-readonly-grid')).not.toBeInTheDocument();
    expect(screen.getByTestId('decision-data-warning')).toHaveTextContent(/blocked setups stay off this list/i);
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
    expect(screen.getByTestId('decision-empty-state')).toHaveTextContent(
      /no qualifying buy candidates in the latest scan/i,
    );
    expect(screen.getByTestId('decision-proof-link')).toHaveAttribute('href', '/proof');
    expect(screen.queryByTestId('card-A')).not.toBeInTheDocument();
  });

  it('does not render a BUY when is_buy_candidate is omitted', () => {
    const omitted = {
      ticker: 'OMIT',
      asset_type: 'stock',
      decision_signal: 'BUY',
      is_top_pick: true,
      selection_rank: 1,
      provider_status: 'ok',
      bar_age_minutes: 3,
      freshness_flags: {},
      readiness_hard_stop: false,
      readiness_score: 90,
      gate_passed: true,
      recommended_action: 'dry_run',
    } as unknown as ScanResult;

    render(<DecisionGrid results={[omitted]} decisions={[]} automation={null} />);
    expect(screen.queryByTestId('card-OMIT')).not.toBeInTheDocument();
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

    expect(screen.getByTestId('card-MSFT')).toBeInTheDocument();
    expect(screen.getByTestId('card-ETH/USD')).toBeInTheDocument();
    expect(screen.queryByTestId('card-INTC')).not.toBeInTheDocument();
    expect(screen.queryByTestId('card-AVAX/USD')).not.toBeInTheDocument();
    expect(screen.queryByTestId('stock-sparse-state')).not.toBeInTheDocument();
    expect(screen.queryByTestId('crypto-sparse-state')).not.toBeInTheDocument();
    // The displayed picks are fresh; a stale row that is not shown must not
    // label the visible results as stale.
    expect(screen.getByTestId('decision-data-warning')).not.toHaveTextContent(/stale/i);
    expect(screen.getByTestId('decision-data-warning')).toHaveTextContent(
      /blocked setups stay off this list/i,
    );
  });

  it('explains why each BUY signal was held back when the list is empty', () => {
    const base = {
      asset_type: 'stock',
      decision_signal: 'BUY',
      is_buy_candidate: true,
      is_top_pick: true,
      bar_age_minutes: 3,
      freshness_flags: {},
      readiness_hard_stop: false,
      readiness_score: 20,
      recommended_action: 'blocked',
      execution_eligibility: 'blocked',
    };
    const lowTrust = {
      ...base,
      ticker: 'LOW',
      selection_rank: 1,
      provider_status: 'ok',
      gate_passed: false,
      gate_reason: 'stock BUY bucket has 4 1h outcomes; need 20',
      gate_checks: [
        { name: 'sample_size', passed: false, detail: 'stock BUY bucket has 4 1h outcomes; need 20' },
      ],
      readiness_reason: 'Low trust: blocked only by sample size, not by a hard safety stop.',
    } as unknown as ScanResult;
    const providerDown = {
      ...base,
      ticker: 'PROV',
      selection_rank: 2,
      provider_status: 'critical',
      gate_passed: true,
      gate_reason: 'Stock signal passed signal-level and score-band evidence gates.',
      readiness_reason: 'Blocked: provider critical.',
    } as unknown as ScanResult;
    const hold = {
      ...base,
      ticker: 'HOLDY',
      decision_signal: 'HOLD',
      is_buy_candidate: false,
      is_top_pick: false,
      provider_status: 'ok',
    } as unknown as ScanResult;

    render(
      <DecisionGrid
        results={[lowTrust, providerDown, hold]}
        topStocks={[lowTrust, providerDown]}
        decisions={[]}
        automation={null}
      />,
    );

    const empty = screen.getByTestId('decision-empty-state');
    expect(empty).toHaveTextContent(/no qualifying buy candidates/i);
    expect(screen.getByTestId('decision-held-back')).toHaveTextContent(/2 BUY signals were held back/i);
    expect(screen.getByTestId('held-back-LOW')).toHaveTextContent(/blocked only by sample size/i);
    expect(screen.getByTestId('held-back-PROV')).toHaveTextContent(/provider critical/i);
    // The passed-gate text must never be presented as a reason for holding back.
    expect(screen.getByTestId('held-back-PROV')).not.toHaveTextContent(/passed/i);
    expect(screen.queryByTestId('held-back-HOLDY')).not.toBeInTheDocument();
    expect(screen.getByTestId('decision-proof-link')).toHaveAttribute('href', '/proof');
  });

  it('reports the signal mix when the scan produced no BUY signals at all', () => {
    const rows = [
      { ticker: 'H1', decision_signal: 'HOLD' },
      { ticker: 'H2', decision_signal: 'HOLD' },
      { ticker: 'S1', decision_signal: 'SELL' },
    ].map(
      (row) =>
        ({
          ...row,
          asset_type: 'stock',
          provider_status: 'ok',
          bar_age_minutes: 3,
          freshness_flags: {},
          readiness_hard_stop: false,
        }) as unknown as ScanResult,
    );

    render(<DecisionGrid results={rows} decisions={[]} automation={null} />);
    expect(screen.getByTestId('decision-empty-state')).toHaveTextContent(
      /no BUY signals \(2 HOLD, 1 SELL\)/i,
    );
    expect(screen.queryByTestId('decision-held-back')).not.toBeInTheDocument();
    expect(screen.queryByTestId('decision-data-warning')).not.toBeInTheDocument();
  });

  it('keeps a fresh blocked BUY off the list without calling the bars stale', () => {
    const link = {
      ticker: 'LINK/USD',
      asset_type: 'crypto',
      decision_signal: 'BUY',
      is_buy_candidate: true,
      is_top_pick: true,
      provider_status: 'degraded',
      bar_age_minutes: 6,
      freshness_flags: { market_bars: 'ok', directional_news: 'missing' },
      gate_passed: false,
      gate_checks: [
        { name: 'sample_size', passed: false, detail: 'crypto BUY bucket has 0 1h outcomes; need 30' },
      ],
      recommended_action: 'blocked',
      execution_eligibility: 'blocked',
      readiness_score: 8,
    } as unknown as ScanResult;

    render(
      <DecisionGrid
        results={[link]}
        topCrypto={[link]}
        decisions={[]}
        automation={null}
      />,
    );

    expect(screen.queryByTestId('card-LINK/USD')).not.toBeInTheDocument();
    expect(screen.getByTestId('decision-empty-state')).toHaveTextContent(/no qualifying buy candidates/i);
    expect(screen.getByTestId('decision-data-warning')).toHaveTextContent(/degraded or incomplete data/i);
    expect(screen.getByTestId('decision-data-warning')).not.toHaveTextContent(/stale/i);
  });

  it('shows at most three candidates per asset and keeps the supplied rank order', () => {
    const stocks = [2, 1, 4, 3].map(
      (rank) =>
        ({
          ticker: `S${rank}`,
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
          selection_rank: rank,
        }) as unknown as ScanResult,
    );

    render(
      <DecisionGrid
        results={stocks}
        topStocks={stocks}
        decisions={[]}
        automation={null}
      />,
    );

    const grid = screen.getByTestId('stock-actionable-grid');
    const rendered = within(grid).getAllByTestId(/^card-S/);
    expect(rendered.map((node) => node.textContent)).toEqual(['S2', 'S1', 'S4']);
    expect(screen.queryByTestId('card-S3')).not.toBeInTheDocument();
  });

  it('states a kill switch without listing blocked candidates as buys', () => {
    const blocked = {
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

    render(
      <DecisionGrid
        results={[blocked]}
        topStocks={[blocked]}
        decisions={[]}
        automation={{ kill_switch_enabled: true, breaker: { state: 'closed' } } as never}
      />,
    );

    expect(screen.queryByTestId('card-NVDA')).not.toBeInTheDocument();
    expect(screen.getByTestId('decision-data-warning')).toHaveTextContent(/kill switch is on/i);
    expect(screen.getByTestId('decision-data-warning')).toHaveTextContent(/paper actions are blocked/i);
    expect(screen.getByTestId('decision-empty-state')).toBeInTheDocument();
  });
});
