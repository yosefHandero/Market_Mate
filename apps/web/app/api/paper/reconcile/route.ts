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
    const response = await fetch(`${getScannerApiBase()}/paper/reconcile`, {
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
            ? `Unable to reconcile paper ledger: ${error.message}`
            : 'Unable to reconcile paper ledger.',
      },
      { status: 502 },
    );
  }
}
