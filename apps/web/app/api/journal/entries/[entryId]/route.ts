import { NextResponse, type NextRequest } from 'next/server';
import { ZodError } from 'zod';
import { formatZodError, journalEntryUpdateSchema } from '@/lib/journal';
import { getScannerApiBase } from '@/lib/scanner-api';
import {
  buildScannerAdminHeaders,
  missingScannerAdminTokenResponse,
  proxyScannerResponse,
} from '@/lib/scanner-admin-proxy';

const ADMIN_TOKEN = process.env.SCANNER_ADMIN_API_TOKEN;

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ entryId: string }> },
) {
  if (!ADMIN_TOKEN) {
    return missingScannerAdminTokenResponse();
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
      headers: buildScannerAdminHeaders(ADMIN_TOKEN, true),
      body: JSON.stringify(payload),
      cache: 'no-store',
    });

    return proxyScannerResponse(response);
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
