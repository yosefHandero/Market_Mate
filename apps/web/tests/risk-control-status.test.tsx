/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { RiskControlStatus } from '@/components/risk-control-status';

describe('RiskControlStatus', () => {
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
  });
});
