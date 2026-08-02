/**
 * @vitest-environment jsdom
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OperatorActionsPanel } from '@/components/operator-actions';

const refreshMock = vi.hoisted(() => vi.fn());
const READYZ_URL = '/api/scan/readyz';
const WORKER_NOT_RUNNING_MESSAGE =
  'Scheduler is on, but the local worker is not running. Auto-scans will not run until the worker starts.';

function renderOperatorActions(props: Record<string, unknown> = {}) {
  return render(
    React.createElement(OperatorActionsPanel, {
      schedulerRunning: false,
      onRefresh: refreshMock,
      feedbackClearMs: 60_000,
      ...props,
    }),
  );
}

function isAppUrl(url: RequestInfo | URL, path: string) {
  const urlStr = String(url);
  return urlStr === path || urlStr.endsWith(path);
}

function createAppFetchMockWithReadyz(
  readyzResponses: Array<ReturnType<typeof readyzResponse>>,
  schedulerResponse = new Response(JSON.stringify({ ok: true })),
) {
  let readyzIndex = 0;
  return vi.fn((url: RequestInfo | URL) => {
    const urlStr = String(url);
    if (isAppUrl(url, '/api/scan/scheduler')) {
      return Promise.resolve(schedulerResponse);
    }
    if (isAppUrl(url, READYZ_URL)) {
      const next = readyzResponses[readyzIndex] ?? readyzResponses[readyzResponses.length - 1];
      readyzIndex += 1;
      return Promise.resolve(next);
    }
    return Promise.reject(new Error(`Unexpected fetch: ${urlStr}`));
  });
}

function createAppFetchMock(
  responses: Array<Response | ((url: string) => Response)>,
) {
  let index = 0;
  return vi.fn((url: RequestInfo | URL) => {
    const urlStr = String(url);
    const next = responses[index];
    index += 1;
    if (typeof next === 'function') {
      return Promise.resolve(next(urlStr));
    }
    if (next) {
      return Promise.resolve(next);
    }
    return Promise.reject(new Error(`Unexpected fetch: ${urlStr}`));
  });
}

function appFetchCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls;
}

function readyzResponse({
  scheduler_enabled = false,
  scheduler_running = false,
  worker_alive,
  next_scan_due_at = null,
  last_scheduler_run_started_at = null,
  last_scheduler_error = null,
}: {
  scheduler_enabled?: boolean;
  scheduler_running?: boolean;
  worker_alive?: boolean;
  next_scan_due_at?: string | null;
  last_scheduler_run_started_at?: string | null;
  last_scheduler_error?: string | null;
} = {}) {
  return new Response(
    JSON.stringify({
      scheduler_enabled,
      scheduler_running,
      worker_alive,
      next_scan_due_at,
      last_scheduler_run_started_at,
      last_scheduler_error,
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  refreshMock.mockReset();
});

beforeEach(() => {
  vi.unstubAllGlobals();
  refreshMock.mockReset();
});

describe('OperatorActions', () => {
  it('starts the scheduler when disabled and readyz confirms the worker is running', async () => {
    const user = userEvent.setup();
    const fetchMock = createAppFetchMock([
      new Response(JSON.stringify({ ok: true })),
      readyzResponse({
        scheduler_enabled: true,
        scheduler_running: false,
        worker_alive: true,
        next_scan_due_at: '2026-05-07T15:00:00Z',
        last_scheduler_run_started_at: '2026-05-07T14:00:00Z',
      }),
    ]);
    vi.stubGlobal('fetch', fetchMock);

    renderOperatorActions({
      schedulerEnabled: false,
      schedulerRunning: false,
    });

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    await waitFor(() => expect(appFetchCalls(fetchMock).length).toBeGreaterThanOrEqual(2));
    const [url, init] = appFetchCalls(fetchMock)[0];
    expect(url).toBe('/api/scan/scheduler');
    expect(JSON.parse(String(init?.body))).toEqual({ action: 'start' });
    expect(appFetchCalls(fetchMock)[1][0]).toBe(READYZ_URL);
    await waitFor(() =>
      expect(screen.getAllByText(/Scheduler and worker are running/).length).toBeGreaterThan(0),
    );
    expect(refreshMock).toHaveBeenCalledOnce();
  });

  it('stops the scheduler when enabled', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal('fetch', fetchMock);

    renderOperatorActions({
      schedulerEnabled: true,
      schedulerRunning: true,
    });

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
    const fetchMock = vi.fn((url: RequestInfo | URL) => {
      if (isAppUrl(url, '/api/scan/scheduler')) {
        return pending;
      }
      return Promise.resolve(
        readyzResponse({
          scheduler_enabled: true,
          scheduler_running: false,
        }),
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    renderOperatorActions({ schedulerRunning: false, readyzPollIntervalMs: 0 });

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));
    expect(await screen.findByRole('button', { name: 'Starting...' })).toBeDisabled();

    resolveResponse(new Response(JSON.stringify({ ok: true })));
    await waitFor(() =>
      expect(screen.getAllByText(WORKER_NOT_RUNNING_MESSAGE).length).toBeGreaterThan(0),
    );
  });

  it('shows unavailable state on 503', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));

    renderOperatorActions({ schedulerRunning: false });

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    expect(await screen.findByText(/Admin controls unavailable/i)).toBeInTheDocument();
  });

  it('does not trigger a scan from the scheduler control', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal('fetch', fetchMock);

    renderOperatorActions({
      schedulerEnabled: true,
      schedulerRunning: true,
    });

    await user.click(screen.getByRole('button', { name: 'Stop scheduler' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).not.toBe('/api/scan/run');
  });

  it('shows impact copy and copy script button when worker banner is visible', () => {
    renderOperatorActions({
      schedulerEnabled: true,
      schedulerRunning: false,
    });

    expect(screen.getByText(/readiness scores drop/i)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Copy start-worker script' }).length).toBeGreaterThan(0);
  });

  it('shows the worker warning when readyz never reports scheduler_running after start', async () => {
    const user = userEvent.setup();
    const fetchMock = createAppFetchMockWithReadyz([
      readyzResponse({
        scheduler_enabled: true,
        scheduler_running: false,
      }),
    ]);
    vi.stubGlobal('fetch', fetchMock);

    renderOperatorActions({
      schedulerEnabled: false,
      schedulerRunning: false,
      readyzPollIntervalMs: 0,
    });

    await user.click(screen.getByRole('button', { name: 'Start scheduler' }));

    await waitFor(() =>
      expect(screen.getAllByText(WORKER_NOT_RUNNING_MESSAGE).length).toBeGreaterThan(0),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Stop scheduler' })).toBeInTheDocument(),
    );
    expect(appFetchCalls(fetchMock).length).toBeGreaterThanOrEqual(2);
    expect(appFetchCalls(fetchMock).slice(1).every(([url]) => url === READYZ_URL)).toBe(true);
  });
});
