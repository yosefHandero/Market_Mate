/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import HomePage from '@/app/page';
import RootLayout, { metadata } from '@/app/layout';

vi.mock('@/lib/api', () => ({
  getAutomationStatus: vi.fn(async () => ({ data: { dry_run_only: true }, error: null })),
  getLatestDecisions: vi.fn(async () => ({ data: [], error: null })),
  getProofSummary: vi.fn(async () => ({
    data: {
      policy_promotion: {
        champion_policy_id: 'hybrid_legacy',
        challenger_policy_id: 'weekly_probability',
        challenger_replayable: true,
        ruler_version: 'ruler-v1',
        ruler_fingerprint: 'ruler-fingerprint-123456',
        champion_decision_fingerprint: 'champion-fingerprint-abcdef',
        challenger_decision_fingerprint: 'challenger-fingerprint-abcdef',
        gates_cleared: false,
        walk_forward_holdout_passed: false,
        summary: 'Promotion gates have not cleared.',
        checks: [],
        paired_returns_total: 0,
        paired_returns_informative: 0,
        paired_returns_both_abstained: 0,
        paired_returns_resolution_clusters: 0,
        paired_returns_cluster_metadata_complete: true,
        paired_returns_superior: false,
        pair_exclusion_counts: {},
        effective_champion_policy_id: 'hybrid_legacy',
        requested_champion_policy_id: 'weekly_probability',
      },
    },
    error: null,
  })),
  getLatestScan: vi.fn(async () => ({
    data: {
      created_at: '2026-05-02T12:00:00.000Z',
      market_status: 'bullish',
      scan_count: 0,
      watchlist_size: 0,
      results: [],
    },
    error: null,
  })),
  getReadyz: vi.fn(async () => ({
    data: {
      scheduler_enabled: true,
      scheduler_running: false,
      worker_alive: true,
    },
    error: null,
  })),
  getSystemReadiness: vi.fn(async () => ({ data: null, error: null })),
}));

vi.mock('@/components/dashboard-status-banner', () => ({
  DashboardStatusBanner: () => React.createElement('div', { 'data-testid': 'status-banner' }),
}));

vi.mock('@/components/decision-grid', () => ({
  DecisionGrid: () => React.createElement('div', { 'data-testid': 'decision-grid' }),
}));

describe('RootLayout navigation', () => {
  it('links Decision and Proof from the top nav with paper mode badge', () => {
    render(
      React.createElement(RootLayout, null, React.createElement('span', null, 'child')),
    );
    expect(screen.getByRole('link', { name: 'Decision' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('link', { name: 'Proof' }).getAttribute('href')).toBe('/proof');
    expect(screen.getByTestId('paper-mode-badge')).toHaveTextContent(/PAPER MODE/i);
    expect(metadata.description).toContain('BUY candidate');
    expect(metadata.description).not.toMatch(/SELL|HOLD/);
  });

  it('renders decision page with status banner and decision grid', async () => {
    render(await HomePage());
    expect(screen.getByRole('heading', { name: 'Buy Candidates' })).toBeInTheDocument();
    expect(screen.getByTestId('status-banner')).toBeInTheDocument();
    expect(screen.getByTestId('decision-policy-status')).toHaveTextContent(/Serving policy/i);
    expect(screen.getByTestId('decision-policy-mismatch')).toHaveTextContent(
      /Requested champion:\s+Weekly probability/i,
    );
    expect(screen.getByTestId('decision-grid')).toBeInTheDocument();
  });
});
