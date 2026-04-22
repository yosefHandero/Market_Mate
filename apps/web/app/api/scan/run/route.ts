import { NextResponse } from 'next/server';
import { getScannerApiBase, readErrorMessage } from '@/lib/scanner-api';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function POST() {
  if (!ADMIN_TOKEN) {
    return NextResponse.json({ detail: 'Server admin token is not configured.' }, { status: 503 });
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/scan/run`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${ADMIN_TOKEN}`,
      },
      cache: 'no-store',
    });

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
