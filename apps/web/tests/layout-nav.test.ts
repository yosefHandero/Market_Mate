/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import HomePage from '@/app/page';
import RootLayout from '@/app/layout';

vi.mock('@/lib/api', () => ({
  getAutomationStatus: vi.fn(async () => ({ data: { scheduler_running: false }, error: null })),
  getLatestDecisions: vi.fn(async () => ({ data: [], error: null })),
  getLatestScan: vi.fn(async () => ({
    data: {
      created_at: '2026-05-02T12:00:00.000Z',
      market_status: 'open',
      scan_count: 0,
      watchlist_size: 0,
    },
    error: null,
  })),
  getPaperLedger: vi.fn(async () => ({ data: [], error: null })),
  getPaperLedgerSummary: vi.fn(async () => ({ data: null, error: null })),
  getReadyz: vi.fn(async () => ({ data: { scheduler_running: false }, error: null })),
}));

vi.mock('@/components/operator-actions', () => ({
  OperatorActions: () => null,
}));

vi.mock('@/components/trading-workspace', () => ({
  TradingWorkspace: () => null,
}));

describe('RootLayout navigation', () => {
  it('links Actions, History, and Validation from the top nav only', () => {
    render(
      React.createElement(
        RootLayout,
        null,
        React.createElement('span', null, 'child'),
      ),
    );
    expect(screen.getByRole('link', { name: 'Actions' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('link', { name: 'History' }).getAttribute('href')).toBe('/history');
    expect(screen.getByRole('link', { name: 'Validation' }).getAttribute('href')).toBe(
      '/validation',
    );
    expect(screen.queryByRole('link', { name: 'Journal' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Review' })).toBeNull();
  });

  it('does not render the dashboard Open Pages section', async () => {
    render(await HomePage());

    expect(screen.queryByRole('heading', { name: 'Open Pages' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Scan history' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Review queue' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Journal' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Validation' })).toBeNull();
  });
});
