/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { EvidenceTracksPanel } from '@/components/evidence-tracks-panel';
import type { EvidenceTrackDescriptor, WeeklyEvidenceProgress } from '@/lib/types';

const contract: EvidenceTrackDescriptor[] = [
  {
    key: 'walk_forward_research',
    label: 'Walk-forward research',
    description: 'In-sample research.',
    is_forward: false,
    counts_toward_real_money: false,
  },
  {
    key: 'live_forward',
    label: 'Live-forward',
    description: 'Forward-collected predictions.',
    is_forward: true,
    counts_toward_real_money: true,
  },
];

describe('EvidenceTracksPanel', () => {
  it('labels totals across campaigns without implying current campaign evidence', () => {
    render(<EvidenceTracksPanel evidence={{ live_forward_samples: 100, min_live_forward_samples: 20, out_of_sample_samples: 5, min_out_of_sample_samples: 10, historical_samples: 500, min_historical_samples: 30, backfilled_replay_samples: 400, min_backfilled_replay_samples: 20, trust_sample_gate_met: false, calibration_sample_gate_met: true } as WeeklyEvidenceProgress} />);
    expect(screen.getByText(/Historical totals across all campaigns/)).toHaveTextContent('not current-campaign counts');
    expect(screen.getByTestId('trust-sample-gate')).toHaveTextContent('Real-money trust blocked');
  });
  it('renders the shared evidence contract legend with pilot-eligibility labels', () => {
    render(<EvidenceTracksPanel evidence={null} contract={contract} />);
    expect(screen.getByTestId('evidence-contract-legend')).toBeInTheDocument();
    expect(screen.getByTestId('evidence-contract-live_forward')).toHaveTextContent(
      'counts toward pilot',
    );
    expect(screen.getByTestId('evidence-contract-walk_forward_research')).toHaveTextContent(
      'context only',
    );
  });

  it('omits the legend when no contract is provided', () => {
    render(<EvidenceTracksPanel evidence={null} />);
    expect(screen.queryByTestId('evidence-contract-legend')).not.toBeInTheDocument();
  });
});
