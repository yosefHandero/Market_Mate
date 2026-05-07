/**
 * @vitest-environment jsdom
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OperatorActions } from '@/components/operator-actions';

const refreshMock = vi.hoisted(() => vi.fn());
const READYZ_URL = 'http://localhost:8005/readyz';
const WORKER_NOT_RUNNING_MESSAGE =
  'Scheduler enabled, but worker is not running. Start it with: python -m app.worker from services/scanner/.';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

function readyzResponse({
  scheduler_enabled = false,
  scheduler_running = false,
  next_scan_due_at = null,
  last_scheduler_run_started_at = null,
  last_scheduler_error = null,
}: {
  scheduler_enabled?: boolean;
  scheduler_running?: boolean;
  next_scan_due_at?: string | null;
  last_scheduler_run_started_at?: string | null;
  last_scheduler_error?: string | null;
} = {}) {
  return new Response(
    JSON.stringify({
      scheduler_enabled,
      scheduler_running,
      next_scan_due_at,
      last_scheduler_run_started_at,
      last_scheduler_error,
    }),
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  refreshMock.mockReset();
});

describe('OperatorActions', () => {
  it('starts the scheduler when disabled and readyz confirms the worker is running', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
      .mockResolvedValueOnce(
        readyzResponse({
          scheduler_enabled: true,
          scheduler_running: true,
          next_scan_due_at: '2026-05-07T15:00:00Z',
          last_scheduler_run_started_at: '2026-05-07T14:00:00Z',
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(OperatorActions, {
        schedulerEnabled: false,
        schedulerRunning: false,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/scan/scheduler');
    expect(JSON.parse(String(init?.body))).toEqual({ action: 'start' });
    expect(fetchMock.mock.calls[1][0]).toBe(READYZ_URL);
    expect(
      await screen.findByText('Scheduler enabled and worker is running'),
    ).toBeInTheDocument();
    expect(refreshMock).toHaveBeenCalledOnce();
  });

  it('stops the scheduler when enabled', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(OperatorActions, {
        schedulerEnabled: true,
        schedulerRunning: true,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Stop scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/scan/scheduler');
    expect(JSON.parse(String(init?.body))).toEqual({ action: 'stop' });
    expect(await screen.findByRole('button', { name: 'Start scheduler' })).toBeInTheDocument();
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

    render(
      React.createElement(OperatorActions, {
        schedulerEnabled: true,
        schedulerRunning: true,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Stop scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).not.toBe('/api/scan/run');
  });

  it('shows the worker warning when readyz never reports scheduler_running after start', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
      .mockResolvedValue(
        readyzResponse({
          scheduler_enabled: true,
          scheduler_running: false,
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(OperatorActions, {
        schedulerEnabled: false,
        schedulerRunning: false,
        readyzPollIntervalMs: 0,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    expect(await screen.findByText(WORKER_NOT_RUNNING_MESSAGE)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(fetchMock.mock.calls.slice(1).every(([url]) => url === READYZ_URL)).toBe(true);
  });

  it('shows success without the worker warning when readyz flips running on attempt 2', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
      .mockResolvedValueOnce(
        readyzResponse({
          scheduler_enabled: true,
          scheduler_running: false,
        }),
      )
      .mockResolvedValueOnce(
        readyzResponse({
          scheduler_enabled: true,
          scheduler_running: true,
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    render(
      React.createElement(OperatorActions, {
        schedulerEnabled: false,
        schedulerRunning: false,
        readyzPollIntervalMs: 0,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    expect(await screen.findByText('Scheduler enabled and worker is running')).toBeInTheDocument();
    expect(screen.queryByText(WORKER_NOT_RUNNING_MESSAGE)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe(READYZ_URL);
    expect(fetchMock.mock.calls[2][0]).toBe(READYZ_URL);
  });
});
