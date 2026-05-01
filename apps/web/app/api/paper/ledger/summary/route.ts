import { NextResponse } from 'next/server';
import { getScannerApiBase } from '@/lib/scanner-api';
import {
  buildScannerReadHeaders,
  getScannerServerReadToken,
  missingScannerReadTokenResponse,
  proxyScannerResponse,
} from '@/lib/scanner-admin-proxy';

export async function GET() {
  const readToken = getScannerServerReadToken();
  if (!readToken) {
    return missingScannerReadTokenResponse();
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/paper/ledger/summary`, {
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
            ? `Unable to load paper ledger summary: ${error.message}`
            : 'Unable to load paper ledger summary.',
      },
      { status: 502 },
    );
  }
}
