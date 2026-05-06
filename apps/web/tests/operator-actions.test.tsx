/**
 * @vitest-environment jsdom
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OperatorActions } from '@/components/operator-actions';

const refreshMock = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  refreshMock.mockReset();
});

describe('OperatorActions', () => {
  it('starts the scheduler when stopped', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal('fetch', fetchMock);

    render(React.createElement(OperatorActions, { schedulerRunning: false }));

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/scan/scheduler');
    expect(JSON.parse(String(init?.body))).toEqual({ action: 'start' });
    expect(refreshMock).toHaveBeenCalledOnce();
  });

  it('stops the scheduler when running', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal('fetch', fetchMock);

    render(React.createElement(OperatorActions, { schedulerRunning: true }));

    await user.click(screen.getByRole('button', { name: 'Stop scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/scan/scheduler');
    expect(JSON.parse(String(init?.body))).toEqual({ action: 'stop' });
  });

  it('shows scheduler busy labels', async () => {
    const user = userEvent.setup();
    let resolveResponse: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending));

    render(React.createElement(OperatorActions, { schedulerRunning: false }));

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));
    expect(await screen.findByRole('button', { name: 'Starting...' })).toBeDisabled();

    resolveResponse(new Response(JSON.stringify({ ok: true })));
  });

  it('shows unavailable state on 503', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));

    render(React.createElement(OperatorActions, { schedulerRunning: false }));

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    expect(await screen.findByText(/Admin controls unavailable/i)).toBeInTheDocument();
  });

  it('does not trigger a scan from the scheduler control', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal('fetch', fetchMock);

    render(React.createElement(OperatorActions, { schedulerRunning: false }));

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).not.toBe('/api/scan/run');
  });
});
