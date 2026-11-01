/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BuyGateDiagnostics } from '@/components/buy-gate-diagnostics';
import type { ScanResult } from '@/lib/types';

function buy(overrides: Partial<ScanResult> = {}): ScanResult {
  return {
    ticker: 'LINK/USD',
    asset_type: 'crypto',
    decision_signal: 'BUY',
    decision_role: 'production',
    is_buy_candidate: true,
    is_top_pick: false,
    provider_status: 'degraded',
    freshness_flags: { market_bars: 'ok', directional_news: 'missing' },
    gate_passed: false,
    recommended_action: 'blocked',
    execution_eligibility: 'blocked',
    readiness_score: 8,
    gate_checks: [
      { name: 'sample_size', passed: false, detail: 'crypto BUY bucket has 0 1h outcomes; need 30' },
      { name: 'win_rate', passed: false, detail: 'crypto win rate 0.00% vs min 55.00%' },
      { name: 'avg_return', passed: false, detail: 'crypto avg return 0.0000% vs min 0.1500%' },
    ],
    ...overrides,
  } as ScanResult;
}

describe('BuyGateDiagnostics', () => {
  it('explains every failed saved check for a detected BUY', () => {
    render(<BuyGateDiagnostics results={[buy(), buy({ ticker: 'SHADOW/USD', decision_role: 'shadow' })]} />);
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('Detected BUY does not authorize a dry-run');
    expect(diagnostics).toHaveTextContent('Saved scan gate checks and saved safety state');
    expect(diagnostics).toHaveTextContent('LINK/USD — Paper action blocked');
    expect(diagnostics).toHaveTextContent('0 1h outcomes; need 30');
    expect(diagnostics).toHaveTextContent('win rate 0.00% vs min 55.00%');
    expect(diagnostics).toHaveTextContent('avg return 0.0000% vs min 0.1500%');
    expect(diagnostics).toHaveTextContent('0 of 3 saved evidence checks passed');
    expect(diagnostics).toHaveTextContent('Insufficient signal-return samples');
    expect(diagnostics).not.toHaveTextContent('Sample-count check passed; measured performance failed');
    expect(diagnostics).toHaveTextContent('Readiness 8/100; need 70');
    expect(diagnostics).toHaveTextContent('Action blocked; need preview or dry_run');
    expect(diagnostics).toHaveTextContent('directional news: missing');
    expect(diagnostics).not.toHaveTextContent('SHADOW/USD');
  });

  it('shows only the failed checks when some saved checks pass', () => {
    render(
      <BuyGateDiagnostics
        results={[buy({
          gate_checks: [
            { name: 'sample_size', passed: true, detail: 'sample size passed' },
            { name: 'win_rate', passed: false, detail: 'crypto win rate 40.00% vs min 55.00%' },
          ],
        })]}
      />,
    );
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('win rate 40.00% vs min 55.00%');
    expect(diagnostics).not.toHaveTextContent('sample size passed');
    expect(diagnostics).toHaveTextContent('1 of 2 saved evidence checks passed');
    expect(diagnostics).toHaveTextContent('Paper action blocked');
  });

  it('distinguishes enough samples with failed measured performance from an immature bucket', () => {
    // Historical observation as a rendering fixture, not a current gate result.
    render(<BuyGateDiagnostics results={[buy({
      ticker: 'AAPL', asset_type: 'stock',
      gate_checks: [
        { name: 'sample_size', passed: true, detail: 'stock BUY bucket has 35 1h outcomes; need 20' },
        { name: 'win_rate', passed: false, detail: 'stock win rate 25.71% vs min 55.00%' },
        { name: 'avg_return', passed: false, detail: 'stock avg return -0.1005% vs min 0.1500%' },
      ],
    })]} />);
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('Sample-count check passed; measured performance failed');
    expect(diagnostics).toHaveTextContent('25.71%');
    expect(diagnostics).toHaveTextContent('-0.1005%');
    expect(diagnostics).not.toHaveTextContent('Insufficient signal-return samples');
    expect(diagnostics).toHaveTextContent('signal-return outcomes, separate from prediction-snapshot progress');
    expect(diagnostics).toHaveTextContent('More resolved rows or elapsed time do not guarantee qualification');
    expect(diagnostics).toHaveTextContent('saved scan checks, not a live recomputation');
    expect(diagnostics).not.toHaveTextContent('With no resolved outcomes');
  });

  it('reports a stored pass without turning it into an order', () => {
    render(
      <BuyGateDiagnostics
        results={[buy({
          provider_status: 'ok',
          freshness_flags: { market_bars: 'ok', directional_news: 'ok' },
          gate_passed: true,
          recommended_action: 'dry_run',
          execution_eligibility: 'eligible',
          readiness_score: 82,
          is_top_pick: true,
          gate_checks: [
            { name: 'sample_size', passed: true, detail: '30 vs 30' },
            { name: 'win_rate', passed: true, detail: 'win rate passed' },
          ],
        })]}
      />,
    );
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('Stored checks allow preview or dry-run');
    expect(diagnostics).toHaveTextContent('Saved evidence gate passed');
    expect(diagnostics).toHaveTextContent('2 of 2 saved evidence checks passed');
    expect(diagnostics).toHaveTextContent('Readiness 82/100; need 70');
    expect(diagnostics).toHaveTextContent('Action dry_run');
    expect(diagnostics).toHaveTextContent('Selected for Decision.');
    expect(diagnostics).toHaveTextContent('does not authorize a dry-run');
  });

  it('leaves missing gate facts unknown', () => {
    render(
      <BuyGateDiagnostics
        results={[buy({
          gate_checks: undefined,
          gate_passed: undefined,
          gate_reason: undefined,
          readiness_score: undefined,
          recommended_action: undefined,
          execution_eligibility: undefined,
          provider_status: undefined,
          freshness_flags: undefined,
        })]}
      />,
    );
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('Paper eligibility unknown');
    expect(diagnostics).toHaveTextContent('Evidence gate results unavailable');
    expect(diagnostics).toHaveTextContent('Readiness unknown; need 70');
    expect(diagnostics).toHaveTextContent('Action unknown');
    expect(diagnostics).toHaveTextContent('Eligibility unknown');
    expect(diagnostics).not.toHaveTextContent('0%');
    expect(diagnostics).not.toHaveTextContent('directional news');
  });

  it('ignores non-BUY rows', () => {
    const { container } = render(
      <BuyGateDiagnostics results={[buy({ ticker: 'AAPL', asset_type: 'stock', decision_signal: 'HOLD' })]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a review restriction and missing news from the saved row', () => {
    render(
      <BuyGateDiagnostics
        results={[buy({
          recommended_action: 'review',
          execution_eligibility: 'review',
          gate_passed: false,
        })]}
      />,
    );
    const diagnostics = screen.getByLabelText('BUY gate diagnostics');
    expect(diagnostics).toHaveTextContent('Paper action blocked');
    expect(diagnostics).toHaveTextContent('Action review; need preview or dry_run');
    expect(diagnostics).toHaveTextContent('Eligibility review');
    expect(diagnostics).toHaveTextContent('directional news: missing');
  });
});
