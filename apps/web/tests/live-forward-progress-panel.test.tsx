/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { LiveForwardProgressPanel } from '@/components/live-forward-progress-panel';
import type { LiveForwardProgress } from '@/lib/types';

const progress: LiveForwardProgress = {
  campaign_id: 'camp-abc123def456',
  campaign_started_at: '2026-07-01T00:00:00Z',
  config_fingerprint: 'fp1234567890abcdef',
  strategy_version: 'v4.1-integrated',
  code_commit: 'abcdef1234',
  selected_count: 8,
  accepted_outside_top_n_count: 3,
  rejected_count: 20,
  resolved_count: 6,
  pending_count: 5,
  resolved_late_count: 2,
  by_asset: [
    {
      asset_type: 'stock',
      selected: 5,
      accepted_outside_top_n: 2,
      rejected: 12,
      resolved: 4,
      pending: 3,
      resolved_late: 1,
    },
    {
      asset_type: 'crypto',
      selected: 3,
      accepted_outside_top_n: 1,
      rejected: 8,
      resolved: 2,
      pending: 2,
      resolved_late: 1,
    },
  ],
  last_scan_at: '2026-07-30T00:00:00Z',
  last_scan_age_minutes: 42,
  scan_gap_exceeded: false,
  max_expected_scan_gap_minutes: 1560,
  note: null,
};

describe('LiveForwardProgressPanel', () => {
  it('always shows the completion-is-not-readiness banner', () => {
    render(<LiveForwardProgressPanel progress={null} />);
    expect(screen.getByTestId('completion-not-readiness-banner')).toHaveTextContent(
      'Application complete ≠ real-money ready.',
    );
  });

  it('renders campaign, per-asset counts, late-resolution and no-gap state', () => {
    render(<LiveForwardProgressPanel progress={progress} />);
    expect(screen.getByTestId('live-forward-campaign')).toHaveTextContent('camp-abc123def456');
    expect(screen.getByTestId('live-forward-asset-stock')).toHaveTextContent('5');
    expect(screen.getByTestId('live-forward-asset-crypto')).toHaveTextContent('3');
    expect(screen.getByTestId('live-forward-late')).toHaveTextContent('resolved after their due date');
    expect(screen.queryByTestId('live-forward-scan-gap')).not.toBeInTheDocument();
  });

  it('surfaces a missed-window warning when the scan gap is exceeded', () => {
    render(
      <LiveForwardProgressPanel
        progress={{
          ...progress,
          scan_gap_exceeded: true,
          note: 'Last scan was 3000 min ago, beyond the 1560-min expected cadence.',
        }}
      />,
    );
    expect(screen.getByTestId('live-forward-scan-gap')).toHaveTextContent('expected cadence');
  });
});
