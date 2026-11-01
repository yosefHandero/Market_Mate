/**
 * @vitest-environment jsdom
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DashboardStatusBanner,
  computeSystemReadiness,
} from '@/components/dashboard-status-banner';
import type {
  AutomationStatusResponse,
  HealthResponse,
  ScanResult,
  ScanRun,
  SystemReadinessResponse,
} from '@/lib/types';

function health(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    ok: true,
    env: 'test',
    app_version: null,
    ready: true,
    live: true,
    schema_ok: true,
    missing_schema_items: [],
    scheduler_running: false,
    worker_alive: false,
    last_worker_heartbeat_at: null,
    last_scan_at: '2026-05-22T12:00:00.000Z',
    last_scan_age_minutes: 5,
    max_stale_minutes: 30,
    scan_fresh: true,
    scheduler_enabled: false,
    scheduler_interval_seconds: 300,
    next_scan_due_at: null,
    last_scheduler_run_started_at: null,
    last_scheduler_run_finished_at: null,
    last_scheduler_error: null,
    trust_window_start: null,
    trust_window_end: null,
    trust_recent_window_days: null,
    trust_total_signals: null,
    trust_evaluated_count: null,
    trust_pending_count: null,
    trust_buy_passed_evaluated_count: null,
    trust_sell_passed_evaluated_count: null,
    trust_threshold_evidence_status: null,
    trust_threshold_source: null,
    trust_threshold_warning_count: null,
    trust_evidence_ready: null,
    pending_due_15m_count: null,
    pending_due_1h_count: null,
    pending_due_1d_count: null,
    request_id: null,
    ...overrides,
  };
}

function automation(overrides: Partial<AutomationStatusResponse> = {}): AutomationStatusResponse {
  return {
    enabled: false,
    phase: 'disabled',
    dry_run_only: true,
    kill_switch_enabled: false,
    scheduler_triggered: false,
    last_processed_run_id: null,
    last_processed_run_at: null,
    last_recovery_at: null,
    requests_made: 0,
    requests_avoided: 0,
    dedupe_hits: 0,
    retries: 0,
    blocked_by_budget: 0,
    blocked_by_gate: 0,
    blocked_by_cooldown: 0,
    blocked_by_circuit: 0,
    recent_status_counts: {},
    budget: {
      hourly_limit: 0,
      hourly_used: 0,
      daily_limit: 0,
      daily_used: 0,
      per_symbol_window_limit: 0,
      per_symbol_window_seconds: 0,
      per_cycle_limit: 0,
    },
    breaker: {
      state: 'closed',
      opened_at: null,
      open_until: null,
      consecutive_failures: 0,
      last_error: null,
      probe_owner: null,
      probe_expires_at: null,
    },
    recent_intents: [],
    candidates_considered: 0,
    candidates_reached_execution_call: 0,
    filter_rate_pct: null,
    ...overrides,
  };
}

function result(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'AAPL',
    asset_type: 'stock',
    provider_status: 'ok',
    bar_age_minutes: 5,
    freshness_flags: {},
    ...overrides,
  } as unknown as ScanResult;
}

function scan(results: ScanResult[] = [result()]): ScanRun {
  return {
    run_id: 'run-1',
    created_at: '2026-05-22T12:00:00.000Z',
    market_status: 'bullish',
    scan_count: results.length,
    watchlist_size: results.length,
    alerts_sent: 0,
    fear_greed_value: null,
    fear_greed_label: null,
    results,
  };
}

function serverReadiness(
  overrides: Partial<SystemReadinessResponse> = {},
): SystemReadinessResponse {
  return {
    status: 'PASS',
    reasons: ['Server says core checks pass'],
    safety_blockers: [],
    automation: {
      scheduler_enabled: false,
      scheduler_running: false,
      worker_alive: false,
      automation_enabled: false,
      automation_phase: 'disabled',
      automation_ready: false,
      dry_run_only: true,
      kill_switch_enabled: false,
      breaker_state: 'closed',
    },
    provider: {
      worst_status: 'ok',
      total_count: 1,
      critical_count: 0,
      degraded_count: 0,
    },
    freshness: {
      last_scan_at: '2026-05-22T12:00:00.000Z',
      last_scan_age_minutes: 5,
      max_stale_minutes: 30,
      scan_fresh: true,
      total_count: 1,
      stale_count: 0,
      severe_stale_count: 0,
    },
    request_id: null,
    ...overrides,
  };
}

describe('DashboardStatusBanner system readiness', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-22T12:05:00Z'));
  });

  afterEach(() => vi.useRealTimers());

  it('keeps six-minute bars fresh while reporting missing auxiliary inputs separately', () => {
    const stock = result({
      bar_as_of: '2026-05-22T11:59:00Z',
      bar_age_minutes: 6,
      freshness_flags: { market_bars: 'ok', options_flow: 'missing' },
    });
    const crypto = result({
      ticker: 'LINK/USD', asset_type: 'crypto',
      bar_as_of: '2026-05-22T11:59:00',
      bar_age_minutes: 6,
      freshness_flags: { market_bars: 'ok', directional_news: 'missing' },
    });
    render(<DashboardStatusBanner health={health()} automation={automation()} latestScan={scan([stock, crypto])} systemReadiness={serverReadiness()} />);
    expect(screen.getByText('Stock bars').parentElement).toHaveTextContent('fresh');
    expect(screen.getByText('Crypto bars').parentElement).toHaveTextContent('fresh');
    expect(screen.getByTestId('bar-freshness-stock')).toHaveTextContent('oldest age 6m');
    expect(screen.getByTestId('bar-freshness-crypto')).toHaveTextContent('oldest age 6m');
    expect(screen.getByTestId('data-quality-banner')).toHaveTextContent('options_flow: missing');
    expect(screen.getByTestId('data-quality-banner')).toHaveTextContent('directional_news: missing');
    expect(screen.getByTestId('data-quality-banner')).not.toHaveTextContent('bars are stale');
    expect(screen.getByText('System').parentElement).toHaveTextContent('WARN');
    expect(stock.freshness_flags).toEqual({ market_bars: 'ok', options_flow: 'missing' });
    expect(crypto.freshness_flags).toEqual({ market_bars: 'ok', directional_news: 'missing' });
  });

  it('does not call fresh bars stale when the provider is critical', () => {
    const stock = result({
      bar_as_of: '2026-05-22T11:59:00Z',
      bar_age_minutes: 6,
      provider_status: 'critical',
      freshness_flags: { market_bars: 'ok' },
    });
    const crypto = result({
      ticker: 'LINK/USD',
      asset_type: 'crypto',
      bar_as_of: '2026-05-22T11:59:00Z',
      bar_age_minutes: 6,
      provider_status: 'critical',
      freshness_flags: { market_bars: 'ok', directional_news: 'missing' },
    });
    render(
      <DashboardStatusBanner
        health={health()}
        automation={automation()}
        latestScan={scan([stock, crypto])}
      />,
    );
    expect(screen.getByText('Stock bars').parentElement).toHaveTextContent('fresh');
    expect(screen.getByText('Crypto bars').parentElement).toHaveTextContent('fresh');
    expect(screen.getByTestId('data-quality-banner')).toHaveTextContent(/critical provider status/i);
    expect(screen.getByTestId('data-quality-banner')).toHaveTextContent('directional_news: missing');
    expect(screen.getByTestId('data-quality-banner')).not.toHaveTextContent('bars are stale');
    const summary = computeSystemReadiness({
      health: health(),
      automation: automation(),
      latestScan: scan([stock, crypto]),
    });
    expect(summary.reasons).not.toContain('Severe global freshness failure');
    expect(summary.reasons).not.toContain('Provider critical with unusable/stale data');
  });

  it('separates scan execution and stock/crypto bar timestamps without changing stored flags', () => {
    const stock = result({ bar_as_of: '2026-05-20T12:00:00Z', freshness_flags: { market_bars: 'stale' } });
    const crypto = result({ ticker: 'BTC/USD', asset_type: 'crypto', bar_as_of: '2026-05-22T12:03:00Z', freshness_flags: { market_bars: 'ok' } });
    render(<DashboardStatusBanner health={health()} automation={automation()} latestScan={scan([stock, crypto])} />);
    expect(screen.getByText('Stock bars').parentElement).toHaveTextContent('>24h stale');
    expect(screen.getByText('Crypto bars').parentElement).toHaveTextContent('fresh');
    expect(screen.getByTestId('scan-execution-time')).toHaveTextContent('2026-05-22T12:00:00.000Z');
    expect(screen.getByTestId('bar-freshness-stock')).toHaveTextContent('2026-05-20T12:00:00Z');
    expect(screen.getByTestId('bar-freshness-crypto')).toHaveTextContent('oldest age 2m');
    expect(screen.getByTestId('data-quality-banner')).not.toHaveTextContent('Crypto bars are stale');
    expect(crypto.freshness_flags).toEqual({ market_bars: 'ok' });
    expect(stock.freshness_flags).toEqual({ market_bars: 'stale' });
  });

  it('ages stored bars and identifies stale provider observations without changing the row', () => {
    vi.setSystemTime(new Date('2026-09-19T12:00:00Z'));
    const row = result({
      asset_type: 'crypto',
      created_at: '2026-09-08T12:00:00Z',
      bar_as_of: '2026-09-08T11:55:00Z',
    });
    const oldScan = { ...scan([row]), created_at: row.created_at, watchlist_size: 69 };
    render(<DashboardStatusBanner health={health({ scan_fresh: false })} automation={automation()} latestScan={oldScan} />);
    expect(screen.getByText('>24h stale')).toBeInTheDocument();
    expect(screen.getByText('ok (last scan)')).toBeInTheDocument();
    expect(screen.getByTestId('stale-scan-banner')).toHaveTextContent('historical snapshots');
    expect(screen.getByTestId('scan-coverage')).toHaveTextContent('1 analyzed results (0 stock, 1 crypto) from 69 configured symbols, including benchmarks');
    expect(row.bar_age_minutes).toBe(5);
    expect(row.provider_status).toBe('ok');
  });

  it('ages legacy stored bar ages from the observation time when bar_as_of is missing', () => {
    const oldScan = { ...scan([result({ created_at: '2026-05-21T12:00:00Z' })]), created_at: '2026-05-21T12:00:00Z' };
    render(<DashboardStatusBanner health={health({ scan_fresh: false })} automation={automation()} latestScan={oldScan} />);
    expect(screen.getByText('>24h stale')).toBeInTheDocument();
    expect(screen.queryByText('fresh', { exact: true })).not.toBeInTheDocument();
  });

  it('uses an absolute recent bar timestamp without adding the stored age again', () => {
    const recentScan = scan([result({ bar_as_of: '2026-05-22T12:00:00Z', bar_age_minutes: 500 })]);
    render(<DashboardStatusBanner health={health()} automation={automation()} latestScan={recentScan} systemReadiness={serverReadiness()} />);
    expect(screen.getByText('fresh', { exact: true })).toBeInTheDocument();
    expect(screen.queryByTestId('stale-scan-banner')).not.toBeInTheDocument();
  });

  it('interprets timezone-naive SQLite bar timestamps as UTC', () => {
    render(<DashboardStatusBanner health={health()} automation={automation()} latestScan={scan([result({ bar_as_of: '2026-05-22T11:00:00' })])} />);
    expect(screen.getByText('stale', { exact: true })).toBeInTheDocument();
    expect(screen.queryByText('fresh', { exact: true })).not.toBeInTheDocument();
  });

  it('passes core system readiness even when scheduler and worker are off', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health({ scheduler_enabled: false, scheduler_running: false, worker_alive: false }),
        automation: automation(),
        latestScan: scan(),
      }),
    );

    const banner = screen.getByRole('region', { name: /dashboard status/i });
    const primary = within(banner).getByTestId('system-health-primary');
    // Slim strip keeps only Paper / System / Provider / Bars.
    expect(within(primary).getByText('System')).toBeInTheDocument();
    expect(within(primary).getByText('PASS')).toBeInTheDocument();
    expect(within(primary).getByText('Provider')).toBeInTheDocument();
    expect(within(primary).getByText('Stock bars')).toBeInTheDocument();
    expect(within(primary).getByText('Crypto bars')).toBeInTheDocument();
    // Worker / Scheduler detail moved into the health-details disclosure.
    expect(within(primary).queryByText('Scheduler')).not.toBeInTheDocument();
    expect(within(primary).queryByText('Worker')).not.toBeInTheDocument();
    expect(within(banner).getByText('Scheduler')).toBeInTheDocument();
    expect(within(banner).getByText('Worker')).toBeInTheDocument();
  });

  it('prefers server system readiness when the endpoint is available', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health(),
        automation: automation(),
        latestScan: scan(),
        systemReadiness: serverReadiness({
          status: 'FAIL',
          reasons: ['Server-side schema gate failed'],
          safety_blockers: ['Server-side schema gate failed'],
        }),
      }),
    );

    const banner = screen.getByRole('region', { name: /dashboard status/i });
    const primary = within(banner).getByTestId('system-health-primary');
    const systemPill = within(primary).getByText('System').parentElement;
    expect(within(primary).getByText('FAIL')).toBeInTheDocument();
    expect(systemPill).toHaveAttribute('title', 'Server-side schema gate failed');
  });

  it('passes system readiness when one unrelated row is stale but global scan is fresh', () => {
    const summary = computeSystemReadiness({
      health: health({ scan_fresh: true, last_scan_age_minutes: 5 }),
      automation: automation(),
      latestScan: scan([
        result({ ticker: 'AAPL', provider_status: 'ok', bar_age_minutes: 5 }),
        result({ ticker: 'TSLA', provider_status: 'critical', bar_age_minutes: 400 }),
      ]),
    });

    expect(summary.status).toBe('PASS');
    expect(summary.reasons).toContain('Core safety and data checks pass');
  });

  it('fails system readiness when the backend is unavailable', () => {
    const summary = computeSystemReadiness({
      health: null,
      automation: automation(),
      latestScan: scan(),
    });

    expect(summary.status).toBe('FAIL');
    expect(summary.reasons).toContain('Backend unavailable');
  });

  it('fails system readiness for kill switch and open breaker safety states', () => {
    expect(
      computeSystemReadiness({
        health: health(),
        automation: automation({ kill_switch_enabled: true }),
        latestScan: scan(),
      }).reasons,
    ).toContain('Kill switch on');

    expect(
      computeSystemReadiness({
        health: health(),
        automation: automation({
          breaker: {
            state: 'open',
            opened_at: null,
            open_until: null,
            consecutive_failures: 2,
            last_error: 'provider down',
            probe_owner: null,
            probe_expires_at: null,
          },
        }),
        latestScan: scan(),
      }).reasons,
    ).toContain('Circuit breaker open');
  });

  it('fails system readiness for severe global stale/provider conditions', () => {
    const summary = computeSystemReadiness({
      health: health({ scan_fresh: false, last_scan_age_minutes: 400 }),
      automation: automation(),
      latestScan: scan([result({ provider_status: 'critical', bar_age_minutes: 400 })]),
    });

    expect(summary.status).toBe('FAIL');
    expect(summary.reasons).toContain('Severe global freshness failure');
    expect(summary.reasons).toContain('Provider critical with unusable/stale data');
  });

  it('fails system readiness when every ticker has severe stale/provider problems', () => {
    const summary = computeSystemReadiness({
      health: health({ scan_fresh: true, last_scan_age_minutes: 5 }),
      automation: automation(),
      latestScan: scan([
        result({ ticker: 'AAPL', provider_status: 'critical', bar_age_minutes: 400 }),
        result({ ticker: 'TSLA', provider_status: 'critical', bar_age_minutes: 500 }),
      ]),
    });

    expect(summary.status).toBe('FAIL');
    expect(summary.reasons).toContain('Severe global freshness failure');
    expect(summary.reasons).toContain('Provider critical with unusable/stale data');
  });

  it('downgrades System to WARN and shows the data-quality banner when one row is critical/stale', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health({ scan_fresh: true, last_scan_age_minutes: 5 }),
        automation: automation(),
        latestScan: scan([
          result({ ticker: 'AAPL', provider_status: 'ok', bar_age_minutes: 5 }),
          result({ ticker: 'GOOGL', provider_status: 'critical', bar_age_minutes: 1500 }),
        ]),
      }),
    );

    const banner = screen.getByRole('region', { name: /dashboard status/i });
    const primary = within(banner).getByTestId('system-health-primary');
    expect(within(primary).getByText('WARN')).toBeInTheDocument();
    expect(within(primary).queryByText('PASS')).not.toBeInTheDocument();
    expect(screen.getByTestId('data-quality-banner')).toHaveTextContent(
      /Stock bars are stale/i,
    );
  });

  it('keeps System PASS with no data-quality banner when all rows are fresh', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health({ scan_fresh: true, last_scan_age_minutes: 5 }),
        automation: automation(),
        latestScan: scan([
          result({ ticker: 'AAPL', provider_status: 'ok', bar_age_minutes: 5 }),
          result({ ticker: 'MSFT', provider_status: 'ok', bar_age_minutes: 31 }),
        ]),
      }),
    );

    const banner = screen.getByRole('region', { name: /dashboard status/i });
    const primary = within(banner).getByTestId('system-health-primary');
    expect(within(primary).getByText('PASS')).toBeInTheDocument();
    expect(within(primary).queryByText('WARN')).not.toBeInTheDocument();
    expect(screen.queryByTestId('data-quality-banner')).not.toBeInTheDocument();
  });

  it('overrides a server PASS to WARN when scan data quality is degraded', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health(),
        automation: automation(),
        latestScan: scan([result({ provider_status: 'critical', bar_age_minutes: 1500 })]),
        systemReadiness: serverReadiness({ status: 'PASS', reasons: ['Server says core checks pass'] }),
      }),
    );

    const banner = screen.getByRole('region', { name: /dashboard status/i });
    const primary = within(banner).getByTestId('system-health-primary');
    expect(within(primary).getByText('WARN')).toBeInTheDocument();
    expect(screen.getByTestId('data-quality-banner')).toBeInTheDocument();
  });

  it('keeps System FAIL (not WARN) when a real blocker exists alongside bad data', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health(),
        automation: automation({ kill_switch_enabled: true }),
        latestScan: scan([result({ provider_status: 'critical', bar_age_minutes: 1500 })]),
      }),
    );

    const banner = screen.getByRole('region', { name: /dashboard status/i });
    const primary = within(banner).getByTestId('system-health-primary');
    expect(within(primary).getByText('FAIL')).toBeInTheDocument();
    expect(within(primary).queryByText('WARN')).not.toBeInTheDocument();
  });

  it('shows safety alert when kill switch is on', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health(),
        automation: automation({ kill_switch_enabled: true }),
        latestScan: scan(),
      }),
    );

    expect(screen.getByRole('status')).toHaveTextContent(/kill switch is on/i);
    expect(screen.getByText(/health details/i)).toBeInTheDocument();
  });

  it('keeps kill switch visible in health details when active', () => {
    render(
      React.createElement(DashboardStatusBanner, {
        health: health(),
        automation: automation({ kill_switch_enabled: true }),
        latestScan: scan(),
      }),
    );

    expect(screen.getByText('Kill switch')).toBeInTheDocument();
    expect(screen.getByText('on')).toBeInTheDocument();
  });
});
