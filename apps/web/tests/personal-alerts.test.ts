/**
 * @vitest-environment jsdom
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PersonalAlerts } from '@/components/personal-alerts';
import {
  buildFrequentWatchTickers,
  personalAlertId,
  shouldNotify,
} from '@/lib/personal-alerts';
import type { JournalEntry, ScanResult, ScanRun } from '@/lib/types';

function sampleResult(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'AAPL',
    asset_type: 'stock',
    score: 82,
    raw_score: 82,
    calibrated_confidence: 82,
    calibration_source: 'fixture',
    confidence_label: 'high',
    strategy_id: 'scanner-directional',
    strategy_version: 'v1',
    strategy_primary_horizon: '1h',
    strategy_entry_assumption: 'Break above high',
    strategy_exit_assumption: 'Trail stop',
    evidence_quality: 'high',
    evidence_quality_score: 0.9,
    evidence_quality_reasons: [],
    data_grade: 'decision',
    execution_eligibility: 'eligible',
    decision_signal: 'BUY',
    explanation: 'Fixture signal.',
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
    options_flow_summary: 'Calls leading.',
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
    created_at: '2026-05-11T15:00:00.000Z',
    ...overrides,
  };
}

function sampleRun(overrides: Partial<ScanRun> = {}): ScanRun {
  const results = overrides.results ?? [sampleResult()];

  return {
    run_id: 'run-1',
    created_at: '2026-05-11T15:01:00.000Z',
    market_status: 'bullish',
    scan_count: results.length,
    watchlist_size: results.length,
    alerts_sent: 0,
    fear_greed_value: null,
    fear_greed_label: null,
    ...overrides,
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
    created_at: '2026-05-10T15:00:00.000Z',
    signal_label: null,
    score: null,
    news_source: null,
    override_reason: null,
    action_state: null,
    ...overrides,
  };
}

function installNotification(permission: NotificationPermission = 'default') {
  const created: Array<{ title: string; options?: NotificationOptions }> = [];
  const requestPermission = vi.fn(async () => 'granted' as NotificationPermission);

  class MockNotification {
    static permission = permission;
    static requestPermission = requestPermission;

    constructor(title: string, options?: NotificationOptions) {
      created.push({ title, options });
    }
  }

  vi.stubGlobal('Notification', MockNotification);

  return { created, requestPermission };
}

function mockVisibility(initial: DocumentVisibilityState) {
  let state = initial;
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => state);

  return {
    set(next: DocumentVisibilityState) {
      state = next;
      document.dispatchEvent(new Event('visibilitychange'));
    },
  };
}

async function clickSwitch() {
  await act(async () => {
    fireEvent.click(screen.getByRole('switch', { name: /browser alerts/i }));
    await Promise.resolve();
  });
}

async function advancePolling(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('personal alerts helper', () => {
  it('returns only watched, ready, unseen scan rows', () => {
    const run = sampleRun({
      results: [
        sampleResult({ ticker: 'AAPL', calibrated_confidence: 82, score: 82 }),
        sampleResult({
          ticker: 'MSFT',
          calibrated_confidence: 69,
          score: 69,
        }),
        sampleResult({ ticker: 'TSLA', calibrated_confidence: 90, score: 90 }),
      ],
    });

    expect(shouldNotify(run, [], 70, ['aapl', 'msft']).map((match) => match.ticker)).toEqual([
      'AAPL',
    ]);
    expect(shouldNotify(run, [personalAlertId('run-1', 'AAPL')], 70, ['AAPL'])).toEqual([]);
  });

  it('builds frequent watcher tickers from watching or took decisions in the last 14 days', () => {
    const tickers = buildFrequentWatchTickers(
      [
        journalEntry({ id: 1, ticker: 'aapl', decision: 'watching' }),
        journalEntry({ id: 2, ticker: 'AAPL', decision: 'took' }),
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
          created_at: '2026-05-09T15:00:00.000Z',
        }),
      ],
      new Date('2026-05-11T15:00:00.000Z'),
    );

    expect(tickers).toEqual(['AAPL', 'BTC']);
  });
});

describe('PersonalAlerts', () => {
  it('defaults off and does not request notification permission on render', () => {
    const { requestPermission } = installNotification();

    render(
      React.createElement(PersonalAlerts, {
        initialLatestScan: null,
        watchTickers: ['AAPL'],
      }),
    );

    expect(screen.getByRole('switch', { name: /browser alerts: off/i })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    expect(requestPermission).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('market-mate.personal-alerts.enabled')).toBeNull();
  });

  it('requests permission only after a click and stores opt-in locally', async () => {
    const { requestPermission } = installNotification();

    render(
      React.createElement(PersonalAlerts, {
        initialLatestScan: null,
        watchTickers: ['AAPL'],
      }),
    );

    await clickSwitch();

    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('switch', { name: /browser alerts: on/i })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(window.localStorage.getItem('market-mate.personal-alerts.enabled')).toBe('true');
  });

  it('polls only while visible and suppresses duplicate run ticker alerts', async () => {
    vi.useFakeTimers();
    const visibility = mockVisibility('hidden');
    const { created } = installNotification('granted');
    const fetchLatestScan = vi.fn(async () => sampleRun());

    render(
      React.createElement(PersonalAlerts, {
        initialLatestScan: null,
        watchTickers: ['AAPL'],
        fetchLatestScan,
      }),
    );

    await clickSwitch();
    await advancePolling(60_000);
    expect(fetchLatestScan).not.toHaveBeenCalled();

    await act(async () => {
      visibility.set('visible');
      await Promise.resolve();
    });

    await advancePolling(30_000);
    expect(fetchLatestScan).toHaveBeenCalledTimes(1);
    expect(created).toHaveLength(1);
    expect(created[0].title).toContain('AAPL');

    await advancePolling(30_000);
    expect(fetchLatestScan).toHaveBeenCalledTimes(2);
    expect(created).toHaveLength(1);
  });

  it('shows a clear hint when browser notification permission is denied', async () => {
    const { requestPermission } = installNotification('denied');

    render(
      React.createElement(PersonalAlerts, {
        initialLatestScan: null,
        watchTickers: ['AAPL'],
      }),
    );

    await clickSwitch();

    expect(requestPermission).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Enable notifications in this browser's site settings/i),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem('market-mate.personal-alerts.enabled')).toBe('false');
  });
});
