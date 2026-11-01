/** @vitest-environment jsdom */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ExecutionAuditList } from '@/components/execution-audit-list';
import { PaperLedgerPanel } from '@/components/paper-ledger-panel';
import type { ExecutionAuditSummary, PaperPositionSummary } from '@/lib/types';

afterEach(() => vi.restoreAllMocks());

it('renders the same naive UTC audit and ledger fill in the same local timezone', () => {
  vi.spyOn(Date.prototype, 'toLocaleString').mockImplementation(function (this: Date) {
    return new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', dateStyle: 'short', timeStyle: 'long' }).format(this);
  });
  const filledAt = '2026-11-01T13:07:26';
  render(<>
    <ExecutionAuditList audits={[{ id: 1, ticker: 'AAPL', side: 'buy', created_at: filledAt, lifecycle_status: 'dry_run', dry_run: true } as ExecutionAuditSummary]} />
    <PaperLedgerPanel positions={[{ id: 1, ticker: 'AAPL', asset_type: 'stock', side: 'buy', status: 'open', quantity: 1, simulated_fill_price: 101, notional_usd: 101, cost_basis_usd: 101, opened_at: filledAt, contract_status: 'recorded', exit_method: 'time_based', holding_duration_seconds: 3600, exit_due_at: '2026-11-01T14:07:26', closure_status: 'scheduled' } as PaperPositionSummary]} summary={null} latestPrices={{ AAPL: 101 }} refreshing={false} onRefresh={vi.fn()} />
  </>);
  expect(screen.getByRole('region', { name: 'Recent dry-run audits' })).toHaveTextContent('11/1/26, 7:07:26 AM CST');
  expect(screen.getByText('Fill: 11/1/26, 7:07:26 AM CST')).toBeInTheDocument();
  expect(screen.getByText('Deadline: 11/1/26, 8:07:26 AM CST')).toBeInTheDocument();
});

