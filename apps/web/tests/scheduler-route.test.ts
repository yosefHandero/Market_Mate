import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

function createSchedulerRequest(action: 'start' | 'stop') {
  return new NextRequest('http://localhost/api/scan/scheduler', {
    method: 'POST',
    body: JSON.stringify({ action }),
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

describe('scheduler route handler', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    delete process.env.SCANNER_ADMIN_API_TOKEN;
    delete process.env.NEXT_PUBLIC_SCANNER_API_BASE;
  });

  it('proxies start scheduling to the scanner admin API', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ started: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/scan/scheduler/route');
    const response = await POST(createSchedulerRequest('start'));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ started: true });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://scanner.test/scan/scheduler/start');
    expect(init?.method).toBe('POST');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer admin-token');
  });

  it('proxies stop scheduling to the scanner admin API', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ stopped: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/scan/scheduler/route');
    const response = await POST(createSchedulerRequest('stop'));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ stopped: true });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://scanner.test/scan/scheduler/stop');
    expect(init?.method).toBe('POST');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer admin-token');
  });
});
