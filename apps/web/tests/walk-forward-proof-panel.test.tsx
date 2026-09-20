/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { WalkForwardProofPanel } from '@/components/walk-forward-proof-panel';
import type { WalkForwardRunSummary } from '@/lib/types';

function makeSummary(overrides: Partial<WalkForwardRunSummary> = {}): WalkForwardRunSummary {
  return {
    run_id: 'wf-abc123',
    created_at: '2026-07-05T00:00:00Z',
    window_start: '2023-07-05T00:00:00Z',
    window_end: '2026-06-24T00:00:00Z',
    holdout_start: '2025-10-05T00:00:00Z',
    target_years: 3,
    step_days: 7,
    forward_days: 7,
    top_n_per_asset: 5,
    symbol_count: 60,
    prediction_count: 420,
    resolved_count: 400,
    pending_count: 20,
    evidence_track: 'historical_walk_forward',
    by_asset_track: [
      {
        asset_type: 'stock',
        track: 'holdout',
        prediction_count: 60,
        resolved_count: 60,
        pending_count: 0,
        upside_hit_rate_pct: 62,
        avg_return_pct: 1.4,
        avg_return_after_friction_pct: 1.3,
        avg_return_after_friction_stressed_pct: 1.1,
        calibration_mean_abs_gap_pct: 6,
        exit_window_helped_rate_pct: 58,
        avg_protected_return_pct: 1.2,
        avg_hold_return_pct: 1.0,
        worst_return_pct: -8,
        p05_return_pct: -5,
        worst_decile_mean_pct: -6,
        max_drawdown_pct: 12,
      },
    ],
    calibration_buckets: [],
    coverage: [],
    pilot_verdict: {
      ready: false,
      real_money_trust_blocked: true,
      summary: 'Historical walk-forward evidence does not yet meet the tiny-pilot review bar.',
      checks: [
        { name: 'stock_min_predictions', passed: true, detail: '60 predictions.' },
        { name: 'stock_holdout_upside_hit_rate', passed: false, detail: 'Holdout upside hit rate 62.' },
      ],
    },
    note: null,
    ...overrides,
  };
}

describe('WalkForwardProofPanel', () => {
  it('renders metrics table and keeps real-money trust blocked', () => {
    render(<WalkForwardProofPanel summary={makeSummary()} />);
    expect(screen.getByTestId('walk-forward-metrics-table')).toBeInTheDocument();
    expect(screen.getByTestId('walk-forward-verdict')).toHaveTextContent('NOT MET');
    expect(screen.getByTestId('walk-forward-trust-note')).toHaveTextContent(
      'Real-money trust remains blocked',
    );
  });

  it('shows a placeholder when no run exists', () => {
    render(<WalkForwardProofPanel summary={null} />);
    expect(screen.getByTestId('walk-forward-placeholder')).toBeInTheDocument();
  });

  it('reports the pilot bar as met when the verdict is ready', () => {
    render(
      <WalkForwardProofPanel
        summary={makeSummary({
          pilot_verdict: {
            ready: true,
            real_money_trust_blocked: true,
            summary: 'Historical walk-forward evidence meets the tiny-pilot review bar.',
            checks: [],
          },
        })}
      />,
    );
    expect(screen.getByTestId('walk-forward-verdict')).toHaveTextContent('MET');
  });

  it('renders independent stock and crypto verdicts and the run manifest', () => {
    render(
      <WalkForwardProofPanel
        summary={makeSummary({
          config_fingerprint: 'abcdef0123456789',
          engine_version: 'wf-engine-v1',
          ruler_version: 'ruler-v2',
          ruler_fingerprint: '1234567890abcdef',
          overlap_status: 'non_overlapping',
          data_quality_ok: true,
          survivorship_caveat: 'Universe is the current watchlist only; survivorship-limited.',
          pilot_verdict: {
            ready: false,
            real_money_trust_blocked: true,
            summary: 'mixed',
            checks: [],
            by_asset: [
              { asset_type: 'stock', ready: true, real_money_trust_blocked: true, summary: 'stock ok', checks: [] },
              { asset_type: 'crypto', ready: false, real_money_trust_blocked: true, summary: 'crypto not yet', checks: [] },
            ],
          },
        })}
      />,
    );
    expect(screen.getByTestId('walk-forward-verdict-stock')).toHaveTextContent('MET');
    expect(screen.getByTestId('walk-forward-verdict-crypto')).toHaveTextContent('NOT MET');
    const manifest = screen.getByTestId('walk-forward-manifest');
    expect(manifest).toHaveTextContent('survivorship-limited');
    expect(manifest).toHaveTextContent('abcdef012345');
    expect(manifest).toHaveTextContent('ruler ruler-v2 / 1234567890ab');
  });
});
