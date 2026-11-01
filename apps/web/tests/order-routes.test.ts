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

  it('forwards authoritative budget sizing and the agreed paper contract without dropping fields', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { POST: preview } = await import('@/app/api/orders/preview/route');
    const previewResponse = await preview(createJsonRequest('http://localhost/api/orders/preview', { ticker: 'BTC/USD', side: 'buy', requested_notional_usd: 100 }));
    expect(previewResponse.status).toBe(200);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({ ticker: 'BTC/USD', side: 'buy', requested_notional_usd: 100, order_type: 'market' });
    const contract = { source_run_id: 'run-1', policy_id: 'hybrid', policy_version: 'v4', decision_fingerprint: 'fingerprint', holding_horizon: '1h', holding_duration_seconds: 3600, exit_method: 'time_based' };
    const { POST: place } = await import('@/app/api/orders/place/route');
    const placeResponse = await place(createJsonRequest('http://localhost/api/orders/place', { ticker: 'BTC/USD', side: 'buy', qty: 0.00123, paper_contract: contract, preview_audit_id: 12 }));
    expect(placeResponse.status).toBe(200);
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual(expect.objectContaining({ qty: 0.00123, paper_contract: contract, dry_run: true }));
  });

  it('rejects contradictory quantity and budget requests without adding an eligibility rule', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { POST } = await import('@/app/api/orders/preview/route');
    const response = await POST(createJsonRequest('http://localhost/api/orders/preview', { ticker: 'AAPL', side: 'buy', qty: 1, requested_notional_usd: 100 }));
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
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

  it('rejects client dry_run false before proxying order placement', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn();
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

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ detail: 'dry_run cannot be false.' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects live order modes before proxying order placement', async () => {
    process.env.SCANNER_ADMIN_API_TOKEN = 'admin-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/api/orders/place/route');
    const response = await POST(
      createJsonRequest('http://localhost/api/orders/place', {
        ticker: 'AAPL',
        side: 'buy',
        qty: 1,
        mode: 'live',
        dry_run: true,
      }),
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ detail: 'mode must be "dry_run".' });
    expect(fetchMock).not.toHaveBeenCalled();
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
