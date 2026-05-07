/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { PersonalReviewDashboard } from '@/components/personal-review-dashboard';
import { buildPersonalReview, type BuildPersonalReviewInput } from '@/lib/personal-review';
import type { ExecutionAuditSummary, PaperPositionSummary } from '@/lib/types';

const emptyInput = (): BuildPersonalReviewInput => ({
  validation: null,
  executionAlignment: null,
  paperLedger: [],
  paperLedgerSummary: null,
  journalEntries: [],
  audits: [],
});

function position(overrides: Partial<PaperPositionSummary> = {}): PaperPositionSummary {
  return {
    id: 1,
    intent_key: 'intent-1',
    execution_audit_id: 100,
    ticker: 'AAPL',
    asset_type: 'stock',
    side: 'buy',
    quantity: 1,
    simulated_fill_price: 100,
    notional_usd: 100,
    cost_basis_usd: 100,
    close_price: 120,
    realized_pnl: 20,
    status: 'closed',
    opened_at: '2026-05-01T14:00:00.000Z',
    closed_at: '2026-05-01T15:00:00.000Z',
    strategy_version: 'v4',
    confidence: 75,
    ...overrides,
  };
}

function audit(overrides: Partial<ExecutionAuditSummary> = {}): ExecutionAuditSummary {
  return {
    id: 100,
    created_at: '2026-05-01T14:00:00.000Z',
    updated_at: '2026-05-01T14:01:00.000Z',
    ticker: 'AAPL',
    asset_type: 'stock',
    side: 'buy',
    order_type: 'market',
    qty: 1,
    dry_run: true,
    lifecycle_status: 'previewed',
    latest_price: 100,
    notional_estimate: 100,
    signal_outcome_id: 1,
    signal_run_id: 'run-1',
    signal_generated_at: '2026-05-01T14:00:00.000Z',
    latest_signal: 'BUY',
    confidence: 75,
    trade_gate_horizon: '1h',
    gate_evaluation_mode: 'validation',
    evidence_basis: 'paper',
    trust_window_start: null,
    trust_window_end: null,
    latest_scan_age_minutes: 2,
    latest_scan_fresh: true,
    stored_gate_passed: true,
    stored_gate_reason: 'Passed',
    gate_consistent_with_signal: true,
    trade_gate_allowed: true,
    trade_gate_reason: 'Passed',
    submitted: false,
    broker_order_id: null,
    broker_status: null,
    error_message: null,
    ...overrides,
  };
}

describe('PersonalReviewDashboard', () => {
  it('renders empty data without NaN', () => {
    const review = buildPersonalReview(emptyInput());
    const { container } = render(React.createElement(PersonalReviewDashboard, { review }));

    expect(screen.getByText('Heuristic review. Outcomes are paper-only.')).toBeInTheDocument();
    expect(screen.getByText('Low sample sizes can be misleading.')).toBeInTheDocument();
    expect(screen.getByText(/No closed paper outcomes are available yet/)).toBeInTheDocument();
    expect(screen.getByText('No validation context is available yet.')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('NaN');
    expect(container).not.toHaveTextContent('Infinity');
  });

  it('renders subgroup tables with baseline columns', () => {
    const review = buildPersonalReview({
      ...emptyInput(),
      paperLedger: [position()],
      audits: [audit()],
    });

    render(React.createElement(PersonalReviewDashboard, { review }));

    expect(screen.getByText('By Readiness Band')).toBeInTheDocument();
    expect(screen.getByText('High readiness')).toBeInTheDocument();
    expect(screen.getAllByText('Baseline win')).toHaveLength(3);
    expect(screen.getAllByText('Baseline avg')).toHaveLength(3);
    expect(screen.getAllByText('n=1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Low sample').length).toBeGreaterThan(0);
  });
});
