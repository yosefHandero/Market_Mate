/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { EvidenceTracksPanel } from '@/components/evidence-tracks-panel';
import type { EvidenceTrackDescriptor } from '@/lib/types';

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
