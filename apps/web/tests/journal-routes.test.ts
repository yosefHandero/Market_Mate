import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

function createJsonRequest(url: string, method: 'POST' | 'PATCH', body: unknown) {
  return new NextRequest(url, {
    method,
    body: JSON.stringify(body),
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

describe('journal route handlers', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    delete process.env.SCANNER_ADMIN_API_TOKEN;
    delete process.env.NEXT_PUBLIC_SCANNER_API_BASE;
  });

  it('returns 503 when the admin token is missing', async () => {
    const { POST } = await import('@/app/api/journal/entries/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/journal/entries', 'POST', {
        ticker: 'AAPL',
        run_id: null,
        decision: 'watching',
        entry_price: null,
        exit_price: null,
        pnl_pct: null,
        signal_label: null,
        score: null,
        news_source: null,
        notes: '',
      }),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: 'Server admin token is not configured.',
    });
  });

  it('rejects invalid journal create payloads before proxying them', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/journal/entries/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/journal/entries', 'POST', {
        ticker: 'AAPL',
        run_id: null,
        decision: 'watching',
        entry_price: null,
        exit_price: 190,
        pnl_pct: null,
        signal_label: null,
        score: null,
        news_source: null,
        notes: '',
      }),
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      detail: 'Exit price requires an entry price.',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('proxies valid create requests to the scanner admin API', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 7, ticker: 'AAPL' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/journal/entries/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/journal/entries', 'POST', {
        ticker: ' aapl ',
        run_id: null,
        decision: 'watching',
        entry_price: 180,
        exit_price: null,
        pnl_pct: null,
        signal_label: null,
        score: null,
        news_source: null,
        notes: 'Initial note',
      }),
    );

    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ id: 7, ticker: 'AAPL' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://scanner.test/journal/entries');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer admin-token');
    expect(JSON.parse(String(init?.body))).toEqual({
        ticker: 'AAPL',
        run_id: null,
        decision: 'watching',
        entry_price: 180,
        exit_price: null,
        pnl_pct: null,
        signal_label: null,
        score: null,
        news_source: null,
        notes: 'Initial note',
        override_reason: null,
      });
  });

  it('rejects non-numeric entry ids for journal updates', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { PATCH } = await import('@/app/api/journal/entries/[entryId]/route');
    const response = await PATCH(
      createJsonRequest('http://localhost/api/journal/entries/not-a-number', 'PATCH', {
        notes: 'Updated',
      }),
      { params: Promise.resolve({ entryId: 'not-a-number' }) },
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      detail: 'Entry id must be numeric.',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
