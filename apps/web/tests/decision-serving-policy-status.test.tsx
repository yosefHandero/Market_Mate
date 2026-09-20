/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { DecisionServingPolicyStatus } from '@/components/decision-serving-policy-status';
import type { PolicyPromotionReport } from '@/lib/types';

function report(overrides: Partial<PolicyPromotionReport> = {}): PolicyPromotionReport {
  return {
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
    requested_champion_policy_id: 'hybrid_legacy',
    ...overrides,
  };
}

describe('DecisionServingPolicyStatus', () => {
  it('shows the effective serving policy unobtrusively', () => {
    render(<DecisionServingPolicyStatus report={report()} />);

    expect(screen.getByTestId('decision-policy-status')).toHaveTextContent(
      /Serving policy:\s+Baseline policy/i,
    );
  });

  it('flags a requested champion that is not actually effective', () => {
    render(
      <DecisionServingPolicyStatus
        report={report({ requested_champion_policy_id: 'weekly_probability' })}
      />,
    );

    expect(screen.getByTestId('decision-policy-mismatch')).toHaveTextContent(
      /Requested champion:\s+Weekly probability/i,
    );
    expect(screen.getByTestId('decision-policy-mismatch')).toHaveTextContent(
      /Effective serving policy remains Baseline policy/i,
    );
    expect(screen.getByTestId('decision-policy-mismatch')).toHaveTextContent(
      /no promotion has occurred/i,
    );
  });

  it('does not show legacy overlay or blend terminology when weekly is serving', () => {
    render(
      <DecisionServingPolicyStatus
        report={report({
          gates_cleared: true,
          effective_champion_policy_id: 'weekly_probability',
          requested_champion_policy_id: 'weekly_probability',
        })}
      />,
    );

    const status = screen.getByTestId('decision-policy-status');
    expect(status).toHaveTextContent(/Serving policy:\s+Weekly probability/i);
    expect(status).not.toHaveTextContent(/legacy|overlay|blend/i);
  });
});
