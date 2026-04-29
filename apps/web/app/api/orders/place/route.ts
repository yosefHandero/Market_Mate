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

  const parsed = await readOrderPayload(request, { forceDryRun: true });
  if (parsed.response) {
    return parsed.response;
  }

  const incomingIdempotencyKey = request.headers.get('x-idempotency-key')?.trim();
  if (incomingIdempotencyKey && !parsed.payload.idempotency_key) {
    parsed.payload.idempotency_key = incomingIdempotencyKey;
  }

  const headers = buildScannerAdminHeaders(ADMIN_TOKEN, true);
  if (incomingIdempotencyKey) {
    headers.set('X-Idempotency-Key', incomingIdempotencyKey);
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/orders/place`, {
      method: 'POST',
      headers,
      body: JSON.stringify(parsed.payload),
      cache: 'no-store',
    });

    return proxyScannerResponse(response);
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          error instanceof Error
            ? `Unable to place dry-run order: ${error.message}`
            : 'Unable to place dry-run order.',
      },
      { status: 502 },
    );
  }
}
