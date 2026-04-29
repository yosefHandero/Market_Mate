import { NextResponse } from 'next/server';
import { getScannerApiBase } from '@/lib/scanner-api';
import {
  buildScannerAdminHeaders,
  missingScannerAdminTokenResponse,
  proxyScannerResponse,
} from '@/lib/scanner-admin-proxy';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function POST() {
  if (!ADMIN_TOKEN) {
    return missingScannerAdminTokenResponse();
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/scan/run`, {
      method: 'POST',
      headers: buildScannerAdminHeaders(ADMIN_TOKEN),
      cache: 'no-store',
    });

    return proxyScannerResponse(response);
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          error instanceof Error
            ? `Unable to trigger scan: ${error.message}`
            : 'Unable to trigger scan.',
      },
      { status: 502 },
    );
  }
}
