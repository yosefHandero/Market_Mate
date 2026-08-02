/**
 * @vitest-environment jsdom
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
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
    expect(within(primary).getByText('Bars')).toBeInTheDocument();
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
      /market data is stale or provider is critical/i,
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
