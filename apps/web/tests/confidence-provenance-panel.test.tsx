/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { ConfidenceProvenancePanel } from '@/components/confidence-provenance-panel';
import type { ScanResult } from '@/lib/types';

function row(signal = 'HOLD', stored = true): ScanResult {
  return {
    ticker: 'BTC/USD', asset_type: 'crypto', decision_signal: signal,
    layer_details: stored ? { confidence: { blend: { source: 'signal', horizon: '1h', score_band: '60-70', sample_count: 12, base_score: 63.5 } } } : {},
  } as unknown as ScanResult;
}

describe('ConfidenceProvenancePanel', () => {
  it('shows stored provenance even when the scan contains no BUY rows', () => {
    render(<ConfidenceProvenancePanel results={[row()]} />);
    expect(screen.getByTestId('confidence-provenance-no-buys')).toHaveTextContent('this scan has no BUY rows');
    expect(screen.getByTestId('confidence-provenance-list')).toHaveTextContent('BTC/USD (HOLD): signal on 1h, band 60-70, samples 12, base 63.50');
    expect(screen.queryByTestId('confidence-provenance-empty')).not.toBeInTheDocument();
  });

  it('labels missing metadata without promising a future scan will supply it', () => {
    render(<ConfidenceProvenancePanel results={[row('HOLD', false)]} />);
    expect(screen.getByTestId('confidence-provenance-empty')).toHaveTextContent('This scan lacks stored confidence blend metadata');
    expect(screen.queryByText(/next scan/i)).not.toBeInTheDocument();
  });

  it('distinguishes BUY rows without metadata from a scan with no BUYs', () => {
    render(<ConfidenceProvenancePanel results={[row(), { ...row('BUY', false), ticker: 'ETH/USD' }]} />);
    expect(screen.getByTestId('confidence-provenance-no-buys')).toHaveTextContent('BUY rows lack stored blend metadata');
    expect(screen.getByTestId('confidence-provenance-no-buys')).not.toHaveTextContent('has no BUY rows');
  });
});
