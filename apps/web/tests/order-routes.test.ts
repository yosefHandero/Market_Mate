import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

function createJsonRequest(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
) {
  return new NextRequest(url, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
  });
}

describe('order proxy routes', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    delete process.env.SCANNER_ADMIN_API_TOKEN;
    delete process.env.SCANNER_READ_API_TOKEN;
    delete process.env.NEXT_PUBLIC_SCANNER_API_BASE;
  });

  it('returns 503 for preview when the admin token is missing', async () => {
    const { POST } = await import('@/app/api/orders/preview/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/preview', {
        ticker: 'AAPL',
        side: 'buy',
        qty: 1,
      }),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: 'Server admin token is not configured.',
    });
  });

  it('returns 503 for placement when the admin token is missing', async () => {
    process.env.SCANNER_READ_API_TOKEN = 'read-token';

    const { POST } = await import('@/app/api/orders/place/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/place', {
        ticker: 'AAPL',
        side: 'buy',
        qty: 1,
        mode: 'dry_run',
      }),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: 'Server admin token is not configured.',
    });
  });

  it('proxies order previews to the scanner admin API', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ticker: 'AAPL', execution_audit_id: 12 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/orders/preview/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/preview', {
        ticker: ' aapl ',
        side: 'BUY',
        qty: '0.5',
      }),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ticker: 'AAPL', execution_audit_id: 12 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://scanner.test/orders/preview');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer admin-token');
    expect(JSON.parse(String(init?.body))).toEqual({
      ticker: 'AAPL',
      side: 'buy',
      qty: 0.5,
      order_type: 'market',
    });
  });

  it('forces dry-run order placement when the client omits mode and dry_run', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, dry_run: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/orders/place/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/place', {
        ticker: 'AAPL',
        side: 'buy',
        qty: 1,
      }),
    );

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      ticker: 'AAPL',
      side: 'buy',
      qty: 1,
      order_type: 'market',
      mode: 'dry_run',
      dry_run: true,
    });
  });

  it('overrides client dry_run false before proxying order placement', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, dry_run: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/orders/place/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/place', {
        ticker: 'AAPL',
        side: 'buy',
        qty: 1,
        mode: 'dry_run',
        dry_run: false,
        preview_audit_id: 12,
      }),
    );

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      ticker: 'AAPL',
      side: 'buy',
      qty: 1,
      order_type: 'market',
      mode: 'dry_run',
      preview_audit_id: 12,
      dry_run: true,
    });
  });

  it('normalizes dry-run order placement before proxying to the scanner admin API', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, dry_run: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/orders/place/route');
    const response = await POST(
      createJsonRequest(
        'http://localhost/api/orders/place',
        {
          ticker: 'AAPL',
          side: 'buy',
          qty: 1,
          mode: 'dry_run',
          preview_audit_id: 12,
        },
        { 'X-Idempotency-Key': 'dashboard-test-key' },
      ),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true, dry_run: true });

    const [url, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(url).toBe('http://scanner.test/orders/place');
    expect(headers.get('Authorization')).toBe('Bearer admin-token');
    expect(headers.get('X-Idempotency-Key')).toBe('dashboard-test-key');
    expect(JSON.parse(String(init?.body))).toEqual({
      ticker: 'AAPL',
      side: 'buy',
      qty: 1,
      order_type: 'market',
      mode: 'dry_run',
      preview_audit_id: 12,
      idempotency_key: 'dashboard-test-key',
      dry_run: true,
    });
  });

  it('rejects invalid preview payloads before proxying', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/orders/preview/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/preview', {
        ticker: '',
        side: 'buy',
        qty: 1,
      }),
    );

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('forwards paper ledger filters using the scanner read token', async () => {
    process.env.SCANNER_READ_API_TOKEN = 'read-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/api/paper/ledger/route');
    const response = await GET(
      new NextRequest('http://localhost/api/paper/ledger?status=open&symbol=AAPL'),
    );

    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0];
    const targetUrl = new URL(String(url));
    expect(targetUrl.origin).toBe('http://scanner.test');
    expect(targetUrl.pathname).toBe('/paper/ledger');
    expect(targetUrl.searchParams.get('status')).toBe('open');
    expect(targetUrl.searchParams.get('symbol')).toBe('AAPL');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer read-token');
  });

  it('falls back to the admin token for paper ledger reads when no read token is configured', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/api/paper/ledger/route');
    const response = await GET(new NextRequest('http://localhost/api/paper/ledger'));

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer admin-token');
  });

  it('forwards paper ledger summary using the scanner read token', async () => {
    process.env.SCANNER_READ_API_TOKEN = 'read-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ open_positions: 0, closed_positions: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/api/paper/ledger/summary/route');
    const response = await GET();

    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://scanner.test/paper/ledger/summary');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer read-token');
  });
});
