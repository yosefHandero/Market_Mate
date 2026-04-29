import { NextResponse, type NextRequest } from 'next/server';
import { getScannerApiBase } from '@/lib/scanner-api';
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

  let body: { action?: string };

  try {
    body = (await request.json()) as { action?: string };
  } catch {
    return NextResponse.json({ detail: 'Request body must be valid JSON.' }, { status: 400 });
  }

  const action = body.action;

  if (action !== 'start' && action !== 'stop') {
    return NextResponse.json({ detail: 'action must be "start" or "stop".' }, { status: 400 });
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/scan/scheduler/${action}`, {
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
            ? `Unable to ${action} scheduler: ${error.message}`
            : `Unable to ${action} scheduler.`,
      },
      { status: 502 },
    );
  }
}
