import { NextResponse, type NextRequest } from 'next/server';
import { parseOrderPayload } from '@/lib/paper-trading';

export type NormalizedOrderPayload = {
  ticker: string;
  side: 'buy' | 'sell';
  qty: number;
  order_type: 'market' | 'limit';
  limit_price?: number | null;
  preview_audit_id?: number | null;
  idempotency_key?: string | null;
  mode?: 'dry_run' | null;
  entry_price?: number | null;
  stop_price?: number | null;
  target_price?: number | null;
  recommended_action_snapshot?: string | null;
  dry_run?: boolean;
};

type NormalizedPayloadResult =
  | { payload: NormalizedOrderPayload; response?: never }
  | { payload?: never; response: NextResponse };
type BadRequestResult = { payload?: never; response: NextResponse };
type RawOrderPayload = Record<string, unknown>;

function badRequest(detail: string): BadRequestResult {
  return { response: NextResponse.json({ detail }, { status: 400 }) };
}

export async function readOrderPayload(
  request: NextRequest,
  options: { forceDryRun?: boolean } = {},
): Promise<NormalizedPayloadResult> {
  let rawPayload: unknown;

  try {
    rawPayload = await request.json();
  } catch {
    return badRequest('Request body must be valid JSON.');
  }

  if (!rawPayload || typeof rawPayload !== 'object') {
    return badRequest('Request body must be a JSON object.');
  }

  let payloadForParsing = rawPayload;
  if (options.forceDryRun) {
    const rawOrderPayload = rawPayload as RawOrderPayload;
    if (rawOrderPayload.dry_run === false) {
      return badRequest('dry_run cannot be false.');
    }
    if (
      Object.prototype.hasOwnProperty.call(rawOrderPayload, 'mode') &&
      rawOrderPayload.mode != null &&
      rawOrderPayload.mode !== 'dry_run'
    ) {
      return badRequest('mode must be "dry_run".');
    }
    payloadForParsing = {
      ...rawOrderPayload,
      ...(Object.prototype.hasOwnProperty.call(rawOrderPayload, 'mode') ? {} : { mode: 'dry_run' }),
      ...(Object.prototype.hasOwnProperty.call(rawOrderPayload, 'dry_run') ? {} : { dry_run: true }),
    };
  }
  const parsed = parseOrderPayload(payloadForParsing, Boolean(options.forceDryRun));
  if (!parsed.ok) {
    return badRequest(parsed.detail);
  }

  const payload: NormalizedOrderPayload = { ...parsed.payload };
  if (options.forceDryRun) {
    payload.mode = 'dry_run';
    payload.dry_run = true;
  }

  return { payload };
}
