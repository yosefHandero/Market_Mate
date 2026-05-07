/**
 * @vitest-environment jsdom
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import {
  buildFrequentWatchers,
  buildWatchlistGroups,
  WatchlistView,
} from '@/components/watchlist-view';
import type { JournalEntry, ScanResult, ScanRun } from '@/lib/types';

function scanRow(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'AAPL',
    asset_type: 'stock',
    score: 82,
    raw_score: 82,
    calibrated_confidence: 82,
    calibration_source: 'fixture',
    confidence_label: 'high',
    strategy_id: 'strategy',
    strategy_version: 'v1',
    strategy_primary_horizon: '1h',
    strategy_entry_assumption: 'entry',
    strategy_exit_assumption: 'exit',
    evidence_quality: 'high',
    evidence_quality_score: 0.9,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Fixture row.',
    price: 100,
    price_change_pct: 1.2,
    relative_volume: 1.1,
    relative_strength_pct: 3,
    sentiment_score: 0.3,
    filing_flag: false,
    breakout_flag: true,
    market_status: 'bullish',
    sector_strength_score: 70,
    options_flow_score: 60,
    options_flow_summary: 'neutral',
    options_flow_bullish: true,
    options_call_put_ratio: 1.2,
    alert_sent: false,
    news_checked: true,
    news_source: 'fixture',
    news_cache_label: null,
    signal_label: 'breakout',
    data_quality: 'ok',
    volatility_regime: 'normal',
    benchmark_ticker: 'SPY',
    benchmark_change_pct: 0.4,
    recommended_action: 'dry_run',
    gate_passed: true,
    gate_reason: 'Passed',
    gate_checks: [],
    coingecko_price_change_pct_24h: null,
    coingecko_market_cap_rank: null,
    fear_greed_value: null,
    fear_greed_label: null,
    provider_status: 'ok',
    provider_warnings: [],
    bar_age_minutes: 5,
    freshness_flags: {},
    created_at: '2026-05-07T15:00:00.000Z',
    ...overrides,
  };
}

function scanRun(results: ScanResult[] = []): ScanRun {
  return {
    run_id: 'run-1',
    created_at: '2026-05-07T15:01:00.000Z',
    market_status: 'bullish',
    scan_count: results.length,
    watchlist_size: results.length,
    alerts_sent: 0,
    fear_greed_value: null,
    fear_greed_label: null,
    results,
  };
}

function journalEntry(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 1,
    ticker: 'AAPL',
    run_id: null,
    decision: 'watching',
    entry_price: null,
    exit_price: null,
    pnl_pct: null,
    notes: '',
    created_at: '2026-05-06T15:00:00.000Z',
    signal_label: null,
    score: null,
    news_source: null,
    override_reason: null,
    action_state: null,
    ...overrides,
  };
}

describe('WatchlistView', () => {
  it('groups latest scan rows by asset_type and removes duplicate tickers', () => {
    const groups = buildWatchlistGroups(
      scanRun([
        scanRow({
          ticker: 'aapl',
          decision_signal: 'SELL',
          created_at: '2026-05-07T14:00:00.000Z',
        }),
        scanRow({ ticker: 'AAPL', decision_signal: 'BUY' }),
        scanRow({
          ticker: 'BTC',
          asset_type: 'crypto',
          decision_signal: 'HOLD',
          recommended_action: 'ignore',
        }),
      ]),
    );

    expect(groups).toHaveLength(2);
    expect(groups[0].assetType).toBe('stock');
    expect(groups[0].rows).toHaveLength(1);
    expect(groups[0].rows[0]).toMatchObject({
      ticker: 'AAPL',
      decisionSignal: 'BUY',
      readinessBand: 'high',
    });
    expect(groups[1].assetType).toBe('crypto');
    expect(groups[1].rows[0].ticker).toBe('BTC');
  });

  it('renders ticker, last decision_signal, and last Readiness band', () => {
    render(
      React.createElement(WatchlistView, {
        latestScan: scanRun([scanRow({ ticker: 'MSFT' })]),
        journalEntries: [],
      }),
    );

    const scanned = screen.getByRole('region', { name: 'Scanned watchlist' });
    expect(within(scanned).getByText('MSFT')).toBeInTheDocument();
    expect(within(scanned).getByText('BUY')).toBeInTheDocument();
    expect(within(scanned).getByText('High')).toBeInTheDocument();
  });

  it('builds frequent watchers from unique watching or took entries in the last 14 days', () => {
    const watchers = buildFrequentWatchers(
      [
        journalEntry({ id: 1, ticker: 'aapl', decision: 'watching' }),
        journalEntry({
          id: 2,
          ticker: 'AAPL',
          decision: 'took',
          created_at: '2026-05-07T14:00:00.000Z',
        }),
        journalEntry({ id: 3, ticker: 'MSFT', decision: 'skipped' }),
        journalEntry({
          id: 4,
          ticker: 'OLD',
          decision: 'watching',
          created_at: '2026-04-01T15:00:00.000Z',
        }),
        journalEntry({
          id: 5,
          ticker: 'BTC',
          decision: 'took',
          created_at: '2026-04-25T15:00:00.000Z',
        }),
      ],
      new Date('2026-05-07T15:00:00.000Z'),
    );

    expect(watchers).toEqual([
      {
        ticker: 'AAPL',
        count: 2,
        lastDecision: 'took',
        lastSeenAt: '2026-05-07T14:00:00.000Z',
      },
      {
        ticker: 'BTC',
        count: 1,
        lastDecision: 'took',
        lastSeenAt: '2026-04-25T15:00:00.000Z',
      },
    ]);
  });

  it('renders safely when latest scan is null and has no edit controls', () => {
    const { container } = render(
      React.createElement(WatchlistView, {
        latestScan: null,
        journalEntries: [],
        now: new Date('2026-05-07T15:00:00.000Z'),
      }),
    );

    expect(screen.getByText('No latest scan rows available yet.')).toBeInTheDocument();
    expect(screen.getByText('No recent watching or took journal decisions in the last 14 days.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
    expect(container).not.toHaveTextContent('NaN');
    expect(container).not.toHaveTextContent('Infinity');
  });
});
