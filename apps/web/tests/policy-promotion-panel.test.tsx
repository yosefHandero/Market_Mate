/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { PolicyPromotionPanel } from '@/components/policy-promotion-panel';
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
    summary:
      'Challenger weekly_probability does not clear promotion gates (walk_forward_holdout, paired_live_shadow_returns).',
    checks: [
      {
        name: 'walk_forward_holdout',
        passed: false,
        detail: 'Walk-forward holdout verdict has not passed.',
      },
      {
        name: 'paired_live_shadow_returns',
        passed: false,
        detail: 'Only 3 informative pairs; need 40 before the paired comparison can support any promotion judgment.',
      },
      {
        name: 'paired_calibration_not_worse',
        passed: true,
        detail: 'No paired Brier sample; calibration gate deferred.',
      },
    ],
    paired_returns_total: 4,
    paired_returns_informative: 3,
    paired_returns_both_abstained: 1,
    paired_returns_resolution_clusters: 2,
    paired_returns_cluster_metadata_complete: true,
    paired_returns_superior: false,
    pair_exclusion_counts: { ambiguous_legacy_or_null_policy: 7 },
    effective_champion_policy_id: 'hybrid_legacy',
    requested_champion_policy_id: 'hybrid_legacy',
    ...overrides,
  };
}

describe('PolicyPromotionPanel', () => {
  it('renders nothing without a report', () => {
    const { container } = render(<PolicyPromotionPanel report={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the standing report with per-gate status', () => {
    render(<PolicyPromotionPanel report={report()} />);
    expect(
      screen.getByRole('heading', { name: 'Champion vs challenger' }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('policy-promotion-summary')).toHaveTextContent(
      'does not clear promotion gates',
    );
    expect(
      screen.getByTestId('policy-promotion-check-walk_forward_holdout'),
    ).toHaveTextContent('not yet');
    expect(
      screen.getByTestId('policy-promotion-check-paired_calibration_not_worse'),
    ).toHaveTextContent('pass');
    expect(screen.getByTestId('policy-promotion-pairs')).toHaveTextContent(
      '3 informative pair(s)',
    );
    expect(screen.getByTestId('policy-promotion-pairs')).toHaveTextContent(
      'from 4 eligible pair(s)',
    );
    expect(screen.getByTestId('policy-promotion-pairs')).toHaveTextContent(
      'with 1 both-abstained',
    );
    expect(screen.getByTestId('policy-promotion-pairs')).toHaveTextContent(
      '2 resolution-week cluster(s)',
    );
    expect(screen.getByTestId('policy-promotion-fingerprints')).toHaveTextContent(
      'champion champion-fi',
    );
    expect(screen.getByTestId('policy-promotion-fingerprints')).toHaveTextContent(
      'challenger challenger-',
    );
    expect(screen.getByTestId('policy-promotion-exclusions')).toHaveTextContent(
      'ambiguous legacy or null policy 7',
    );
    expect(screen.getByText(/ruler-v1, ruler-fing/)).toBeInTheDocument();
    expect(screen.queryByTestId('policy-promotion-blocked')).not.toBeInTheDocument();
  });

  it('states when clustered promotion metadata is incomplete', () => {
    render(
      <PolicyPromotionPanel
        report={report({ paired_returns_cluster_metadata_complete: false })}
      />,
    );

    expect(screen.getByTestId('policy-promotion-pairs')).toHaveTextContent(
      'Resolution-week metadata is incomplete',
    );
  });

  it('flags a requested champion that is not in effect', () => {
    render(
      <PolicyPromotionPanel
        report={report({ requested_champion_policy_id: 'weekly_probability' })}
      />,
    );
    expect(screen.getByTestId('policy-promotion-blocked')).toHaveTextContent(
      'promotion gates have not cleared',
    );
  });
});
