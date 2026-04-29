import { NextResponse, type NextRequest } from 'next/server';
import { getScannerApiBase } from '@/lib/scanner-api';
import { readOrderPayload } from '@/lib/order-proxy';
import {
  buildScannerAdminHeaders,
  missingScannerAdminTokenResponse,
  proxyScannerResponse,
} from '@/lib/scanner-admin-proxy';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function POST(request: NextRequest) {
  if (!ADMIN_TOKEN) {
    return missingScannerAdminTokenResponse();
  }

  const parsed = await readOrderPayload(request);
  if (parsed.response) {
    return parsed.response;
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/orders/preview`, {
      method: 'POST',
      headers: buildScannerAdminHeaders(ADMIN_TOKEN, true),
      body: JSON.stringify(parsed.payload),
      cache: 'no-store',
    });

    return proxyScannerResponse(response);
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          error instanceof Error
            ? `Unable to preview dry-run order: ${error.message}`
            : 'Unable to preview dry-run order.',
      },
      { status: 502 },
    );
  }
}
