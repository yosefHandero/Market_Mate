import { NextRequest, NextResponse } from 'next/server';
import { ZodError } from 'zod';
import { formatZodError, journalEntryUpdateSchema } from '@/lib/journal';
import { getScannerApiBase, readErrorMessage } from '@/lib/scanner-api';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ entryId: string }> },
) {
  if (!ADMIN_TOKEN) {
    return NextResponse.json({ detail: 'Server admin token is not configured.' }, { status: 503 });
  }

  let rawPayload: unknown;

  try {
    rawPayload = await request.json();
  } catch {
    return NextResponse.json({ detail: 'Request body must be valid JSON.' }, { status: 400 });
  }

  try {
    const { entryId } = await params;
    if (!/^\d+$/.test(entryId)) {
      return NextResponse.json({ detail: 'Entry id must be numeric.' }, { status: 400 });
    }

    const payload = journalEntryUpdateSchema.parse(rawPayload);
    const response = await fetch(`${getScannerApiBase()}/journal/entries/${entryId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ADMIN_TOKEN}`,
      },
      body: JSON.stringify(payload),
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

    if (error instanceof ZodError) {
      return NextResponse.json({ detail: formatZodError(error) }, { status: 400 });
    }

    return NextResponse.json(
      {
        detail:
          error instanceof Error
            ? `Unable to update journal entry: ${error.message}`
            : 'Unable to update journal entry.',
      },
      { status: 502 },
    );
  }
}
