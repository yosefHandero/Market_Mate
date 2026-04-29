/**
 * @vitest-environment jsdom
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { DecisionPanel, operationalSupportLabel } from '@/components/decision-panel';
import { simulateDecisionPortfolio } from '@/lib/decision-simulation';
import type { DecisionRow } from '@/lib/types';

const sampleRow = (over: Partial<DecisionRow> = {}): DecisionRow => ({
  symbol: 'AAPL',
  asset_type: 'stock',
  signal: 'BUY',
  confidence: 72,
  raw_score: 68,
  calibration_source: 'signal',
  confidence_label: 'moderate_evidence',
  evidence_quality: 'high',
  evidence_quality_score: 0.85,
  evidence_quality_reasons: [],
  data_grade: 'decision',
  execution_eligibility: 'eligible',
  provider_status: 'ok',
  gate_passed: true,
  bar_age_minutes: 5,
  signal_age_minutes: 5,
  freshness_flags: null,
  recommended_action: 'review',
  score_contributions: {},
  strategy_version: 'v3',
  short_metric_summary: '—',
  last_updated: '2026-03-20T12:00:00.000Z',
  ...over,
});

describe('DecisionPanel compact (homepage)', () => {
  it('shows action-first columns without raw score in the main table', () => {
    render(React.createElement(DecisionPanel, { variant: 'compact', rows: [sampleRow()] }));
    expect(screen.getByText('Operational support')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByText('Eligible')).toBeInTheDocument();
    expect(screen.queryByText(/Raw score/i)).not.toBeInTheDocument();
  });

  it('maps execution eligibility to operational support labels', () => {
    expect(operationalSupportLabel(sampleRow({ execution_eligibility: 'review' }))).toBe('Review');
    expect(operationalSupportLabel(sampleRow({ execution_eligibility: 'blocked' }))).toBe('Blocked');
    expect(
      operationalSupportLabel(sampleRow({ signal: 'HOLD', execution_eligibility: 'not_applicable' })),
    ).toBe('—');
  });

  it('renders simulation values alongside sample decision rows', () => {
    const rows = [sampleRow()];
    const simulation = simulateDecisionPortfolio(rows, { 'STOCK:AAPL': 100 });

    render(React.createElement(DecisionPanel, { variant: 'compact', rows, simulation }));

    expect(screen.getByText('Simulation')).toBeInTheDocument();
    expect(screen.getAllByText('Buy').length).toBeGreaterThan(0);
    expect(screen.getByText('Price $100.00')).toBeInTheDocument();
    expect(screen.getByText('$50.00 · 0.5 units')).toBeInTheDocument();
    expect(screen.getByText('Simulation details')).toBeInTheDocument();
  });

  it('does not render inline paper-trade controls', () => {
    render(React.createElement(DecisionPanel, { variant: 'compact', rows: [sampleRow()] }));

    expect(screen.queryByText('Paper trade')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Preview' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Place dry run' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/paper quantity/i)).not.toBeInTheDocument();
  });
});

describe('DecisionPanel default (secondary surfaces)', () => {
  it('keeps evidence quality and ranking score labels distinct', () => {
    render(React.createElement(DecisionPanel, { variant: 'default', rows: [sampleRow()] }));
    expect(screen.getByText('Evidence quality')).toBeInTheDocument();
    expect(screen.getByText('Calibrated ranking score')).toBeInTheDocument();
    const details = screen.getByText('View details').closest('details');
    expect(details).toBeTruthy();
    if (details) {
      expect(within(details as HTMLElement).getByText(/Execution eligibility/i)).toBeInTheDocument();
    }
  });
});
