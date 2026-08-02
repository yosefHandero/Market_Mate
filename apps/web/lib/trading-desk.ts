import { readErrorMessage } from '@/lib/scanner-api';
import type {
  OrderPlaceRequest,
  OrderPlaceResponse,
  OrderPreviewRequest,
  OrderPreviewResponse,
  PaperLedgerSummary,
  PaperPositionSummary,
} from '@/lib/types';

export async function previewOrder(payload: OrderPreviewRequest): Promise<OrderPreviewResponse> {
  const response = await fetch('/api/orders/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as OrderPreviewResponse;
}

export async function placeOrder(payload: OrderPlaceRequest): Promise<OrderPlaceResponse> {
  const response = await fetch('/api/orders/place', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(payload.idempotency_key ? { 'X-Idempotency-Key': payload.idempotency_key } : {}),
    },
    body: JSON.stringify({ ...payload, mode: 'dry_run', dry_run: true }),
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as OrderPlaceResponse;
}

export async function getPaperLedger({
  limit = 100,
  offset = 0,
  symbol,
  status,
}: {
  limit?: number;
  offset?: number;
  symbol?: string | null;
  status?: 'open' | 'closed' | null;
} = {}): Promise<PaperPositionSummary[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (symbol) params.set('symbol', symbol);
  if (status) params.set('status', status);

  const response = await fetch(`/api/paper/ledger?${params.toString()}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as PaperPositionSummary[];
}

export async function getPaperLedgerSummary(): Promise<PaperLedgerSummary> {
  const response = await fetch('/api/paper/ledger/summary', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as PaperLedgerSummary;
}
