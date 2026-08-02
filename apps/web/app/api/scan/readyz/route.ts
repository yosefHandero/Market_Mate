import { NextResponse } from 'next/server';
import { getScannerApiBase, getServerReadHeaders } from '@/lib/scanner-api';
import { proxyScannerResponse } from '@/lib/scanner-admin-proxy';

export async function GET() {
  try {
    const response = await fetch(`${getScannerApiBase()}/readyz`, {
      method: 'GET',
      headers: getServerReadHeaders(),
      cache: 'no-store',
    });

    return proxyScannerResponse(response);
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          error instanceof Error
            ? `Unable to reach scanner readyz: ${error.message}`
            : 'Unable to reach scanner readyz.',
      },
      { status: 502 },
    );
  }
}
