/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReadinessPopover } from '@/components/readiness-popover';
import type { TradeReadiness } from '@/lib/readiness';

const readiness: TradeReadiness = {
  score: 82,
  tone: 'high',
  band: 'high',
  reason: 'Actionable: gates passed and data is fresh.',
  reasons: ['Actionable: gates passed and data is fresh.'],
  action: 'preview',
  baseScore: 82,
  projection: 'stable',
  hardStop: false,
  factors: [
    { key: 'signal_confidence', label: 'Signal confidence', score: 82, reason: 'Strong signal.' },
    { key: 'actionability', label: 'Actionability', score: 92, reason: 'Previewable.' },
    { key: 'gate_status', label: 'Gate status', score: 90, reason: 'Gates passed.' },
    { key: 'provider_health', label: 'Provider health', score: 90, reason: 'Provider OK.' },
    { key: 'freshness', label: 'Freshness', score: 90, reason: 'Fresh.' },
    { key: 'risk_setup', label: 'Risk setup', score: 88, reason: 'Usable.' },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ReadinessPopover', () => {
  it('opens on hover', async () => {
    const user = userEvent.setup();
    render(React.createElement(ReadinessPopover, { readiness }));

    const trigger = screen.getByRole('button', { name: /82%/ });
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveAttribute('data-open', 'false');

    await user.hover(trigger);
    expect(tooltip).toHaveAttribute('data-open', 'true');
  });

  it('opens on focus and closes on Escape', async () => {
    const user = userEvent.setup();
    render(React.createElement(ReadinessPopover, { readiness }));

    const trigger = screen.getByRole('button', { name: /82%/ });
    const tooltip = screen.getByRole('tooltip');

    await user.tab();
    expect(trigger).toHaveFocus();
    expect(tooltip).toHaveAttribute('data-open', 'true');

    await user.keyboard('{Escape}');
    expect(tooltip).toHaveAttribute('data-open', 'false');
  });

  it('does not fetch on hover', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(React.createElement(ReadinessPopover, { readiness }));

    await user.hover(screen.getByRole('button', { name: /82%/ }));

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
