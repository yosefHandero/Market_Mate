/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { ConfidencePerformancePanel } from '@/components/confidence-performance-panel';

describe('ConfidencePerformancePanel', () => {
  it('renders ranking and calibration tables', () => {
    render(
      <ConfidencePerformancePanel
        performance={{
          ranking: {
            buckets: [
              {
                score_band: '80-89',
                asset_type: 'stock',
                signal: 'BUY',
                sample_source: 'live_paper_forward',
                evaluated_count: 5,
                win_rate_pct: 60,
                avg_return_pct: 1.2,
                avg_return_after_friction_base_pct: 1.1,
                avg_return_after_friction_stressed_pct: 1.0,
              },
            ],
            monotonic_by_group: true,
            note: 'Higher-confidence bands are not underperforming lower bands in the resolved sample.',
          },
          calibration: {
            buckets: [
              {
                probability_band: '70-79',
                asset_type: 'stock',
                evaluated_count: 4,
                avg_predicted_pct: 72,
                realized_up_rate_pct: 50,
                reliability_gap_pct: 22,
              },
            ],
            mean_abs_reliability_gap_pct: 22,
            note: 'Predicted upside probability vs realized up-rate.',
          },
        }}
      />,
    );
    expect(screen.getByTestId('confidence-ranking-table')).toBeInTheDocument();
    expect(screen.getByTestId('confidence-calibration-table')).toBeInTheDocument();
    expect(screen.getByTestId('confidence-ranking-verdict')).toHaveTextContent(
      'Higher-confidence bands are not underperforming',
    );
  });
});
