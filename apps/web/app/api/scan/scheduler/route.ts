import { NextRequest, NextResponse } from 'next/server';
import { getScannerApiBase, readErrorMessage } from '@/lib/scanner-api';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function POST(request: NextRequest) {
  if (!ADMIN_TOKEN) {
    return NextResponse.json({ detail: 'Server admin token is not configured.' }, { status: 503 });
  }

  let body: { action?: string };

  try {
    body = (await request.json()) as { action?: string };
  } catch {
    return NextResponse.json({ detail: 'Request body must be valid JSON.' }, { status: 400 });
  }

  const action = body.action;

  if (action !== 'start' && action !== 'stop') {
    return NextResponse.json(
      { detail: 'action must be "start" or "stop".' },
      { status: 400 },
    );
  }

  try {
    const response = await fetch(`${getScannerApiBase()}/scan/scheduler/${action}`, {
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
            ? `Unable to ${action} scheduler: ${error.message}`
            : `Unable to ${action} scheduler.`,
      },
      { status: 502 },
    );
  }
}
