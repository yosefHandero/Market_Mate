import { NextResponse, type NextRequest } from 'next/server';
import { getScannerApiBase } from '@/lib/scanner-api';
import {
  buildScannerAdminHeaders,
  missingScannerAdminTokenResponse,
  proxyScannerResponse,
} from '@/lib/scanner-admin-proxy';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function GET(request: NextRequest) {
  if (!ADMIN_TOKEN) {
    return missingScannerAdminTokenResponse();
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
      headers: buildScannerAdminHeaders(ADMIN_TOKEN),
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
