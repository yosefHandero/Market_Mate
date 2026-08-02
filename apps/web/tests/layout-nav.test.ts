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
    expect(screen.getByTestId('decision-grid')).toBeInTheDocument();
  });
});
