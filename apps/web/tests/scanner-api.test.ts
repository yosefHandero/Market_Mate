import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchScannerJson, readErrorMessage } from '@/lib/scanner-api';

describe('scanner-api helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.SCANNER_READ_API_TOKEN;
    delete process.env.NEXT_PUBLIC_SCANNER_API_BASE;
  });

  it('reads detail messages from JSON error responses', async () => {
    const response = new Response(JSON.stringify({ detail: 'Scanner unavailable.' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });

    await expect(readErrorMessage(response)).resolves.toBe('Scanner unavailable.');
  });

  it('attaches the server read token for protected scanner reads', async () => {
    process.env.SCANNER_READ_API_TOKEN = 'read-token';
    process.env.NEXT_PUBLIC_SCANNER_API_BASE = 'http://scanner.test';

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchScannerJson<{ ok: boolean }>('/readyz')).resolves.toEqual({ ok: true });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get('Authorization')).toBe('Bearer read-token');
  });

  it('surfaces a helpful network error when the scanner API is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED')));

    await expect(fetchScannerJson('/readyz')).rejects.toThrow(
      'Unable to reach scanner API: connect ECONNREFUSED',
    );
  });
});
