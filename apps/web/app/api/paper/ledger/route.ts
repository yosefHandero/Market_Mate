import { NextResponse, type NextRequest } from 'next/server';
import { getScannerApiBase } from '@/lib/scanner-api';
import {
  buildScannerReadHeaders,
  getScannerServerReadToken,
  missingScannerReadTokenResponse,
  proxyScannerResponse,
} from '@/lib/scanner-admin-proxy';

export async function GET(request: NextRequest) {
  const readToken = getScannerServerReadToken();
  if (!readToken) {
    return missingScannerReadTokenResponse();
  }

  const sourceUrl = new URL(request.url);
  const targetUrl = new URL(`${getScannerApiBase()}/paper/ledger`);

  for (const key of ['limit', 'offset', 'symbol', 'status']) {
    const value = sourceUrl.searchParams.get(key);
    if (value) {
      targetUrl.searchParams.set(key, value);
    }
  }

  try {
    const response = await fetch(targetUrl, {
      method: 'GET',
      headers: buildScannerReadHeaders(readToken),
      cache: 'no-store',
    });

    return proxyScannerResponse(response);
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          error instanceof Error
            ? `Unable to load paper ledger: ${error.message}`
            : 'Unable to load paper ledger.',
      },
      { status: 502 },
    );
  }
}
