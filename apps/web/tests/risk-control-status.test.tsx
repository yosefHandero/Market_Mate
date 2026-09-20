/**
 * @vitest-environment jsdom
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { RiskControlStatus } from '@/components/risk-control-status';
import type { HealthResponse, SystemReadinessResponse } from '@/lib/types';

describe('RiskControlStatus', () => {
  it('does not show a degraded provider as healthy', () => {
    render(<RiskControlStatus health={{ scan_fresh: true } as HealthResponse} automation={null} systemReadiness={{ provider: { worst_status: 'degraded', critical_count: 0 } } as SystemReadinessResponse} />);
    const providerPill = screen.getByText('Provider').parentElement!;
    expect(within(providerPill).getByText('degraded')).toBeInTheDocument();
    expect(providerPill).toHaveClass('amber');
    expect(providerPill).not.toHaveClass('green');
  });

  it('states broker submission is removed rather than merely disabled', () => {
    render(
      <RiskControlStatus
        health={null}
        automation={null}
        systemReadiness={null}
        marketStatus={null}
      />,
    );

    // Paper-only build: the panel must not imply live trading is a toggle.
    expect(screen.getByText('Broker submission')).toBeInTheDocument();
    expect(screen.getByText('removed')).toBeInTheDocument();
    expect(screen.queryByText('Live trading')).not.toBeInTheDocument();
    const freshnessPill = screen.getByText('Scan fresh').parentElement!;
    expect(within(freshnessPill).getByText('unknown')).toBeInTheDocument();
    expect(within(freshnessPill).queryByText('yes')).not.toBeInTheDocument();
    expect(freshnessPill).not.toHaveClass('green');
    expect(screen.getByText('Provider').parentElement).not.toHaveClass('green');
  });
});
