import { NextResponse } from 'next/server';
import { readErrorMessage } from '@/lib/scanner-api';

export function missingScannerAdminTokenResponse() {
  return NextResponse.json({ detail: 'Server admin token is not configured.' }, { status: 503 });
}

export function missingScannerReadTokenResponse() {
  return NextResponse.json({ detail: 'Server scanner read token is not configured.' }, { status: 503 });
}

export function getScannerServerReadToken() {
  return process.env.SCANNER_READ_API_TOKEN || process.env.SCANNER_ADMIN_API_TOKEN || '';
}

export function buildScannerAdminHeaders(adminToken: string, jsonBody = false): Headers {
  const headers = new Headers({
    Authorization: `Bearer ${adminToken}`,
  });

  if (jsonBody) {
    headers.set('Content-Type', 'application/json');
  }

  return headers;
}

export async function proxyScannerResponse(response: Response): Promise<NextResponse> {
  if (!response.ok) {
    return NextResponse.json(
      { detail: await readErrorMessage(response) },
      { status: response.status },
    );
  }

  return new NextResponse(await response.text(), {
    status: response.status,
    headers: {
      'Content-Type': response.headers.get('content-type') || 'application/json',
    },
  });
}
