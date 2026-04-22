import {
  AutomationStatusResponse,
  DecisionRow,
  ExecutionAuditSummary,
  ExecutionAlignmentResponse,
  HealthResponse,
  JournalAnalytics,
  JournalEntry,
  JournalEntryCreateRequest,
  JournalEntryUpdateRequest,
  PaperLedgerSummary,
  PaperPositionSummary,
  ReconciliationReportResponse,
  ScanRun,
  ThresholdSweepResponse,
  ValidationSummary,
} from '@/lib/types';
import { fetchScannerJson, readErrorMessage } from '@/lib/scanner-api';

export type ApiResult<T> = {
  data: T | null;
  error: string | null;
};

async function readApiResult<T>(path: string): Promise<ApiResult<T>> {
  try {
    return {
      data: await fetchScannerJson<T>(path),
      error: null,
    };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : 'Unknown request error.',
    };
  }
}

export async function getLatestScan(): Promise<ApiResult<ScanRun | null>> {
  return readApiResult<ScanRun | null>('/scan/latest');
}

export async function getScanHistory(limit = 12): Promise<ApiResult<ScanRun[]>> {
  return readApiResult<ScanRun[]>(`/scan/history?limit=${limit}`);
}
export async function getJournalEntries(limit = 50): Promise<ApiResult<JournalEntry[]>> {
  return readApiResult<JournalEntry[]>(`/journal/entries?limit=${limit}`);
}

export async function createJournalEntry(
  payload: JournalEntryCreateRequest,
): Promise<JournalEntry> {
  const res = await fetch(`/api/journal/entries`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  return (await res.json()) as JournalEntry;
}
export async function updateJournalEntry(
  entryId: number,
  payload: JournalEntryUpdateRequest,
): Promise<JournalEntry> {
  const res = await fetch(`/api/journal/entries/${entryId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  return (await res.json()) as JournalEntry;
}

export async function getJournalAnalytics(): Promise<ApiResult<JournalAnalytics>> {
  return readApiResult<JournalAnalytics>('/journal/analytics');
}

export async function getLatestDecisions(limit = 20): Promise<ApiResult<DecisionRow[]>> {
  return readApiResult<DecisionRow[]>(`/dashboard/decisions/latest?limit=${limit}`);
}

export async function getValidationSummary(): Promise<ApiResult<ValidationSummary>> {
  return readApiResult<ValidationSummary>('/signals/validation/summary');
}

export async function getThresholdSweep(): Promise<ApiResult<ThresholdSweepResponse>> {
  return readApiResult<ThresholdSweepResponse>('/signals/validation/threshold-sweep');
}

export async function getExecutionAlignment(): Promise<ApiResult<ExecutionAlignmentResponse>> {
  return readApiResult<ExecutionAlignmentResponse>('/signals/validation/execution-alignment');
}

export async function getReadyz(): Promise<ApiResult<HealthResponse>> {
  return readApiResult<HealthResponse>('/readyz');
}

export async function getExecutionAudits(limit = 50): Promise<ApiResult<ExecutionAuditSummary[]>> {
  return readApiResult<ExecutionAuditSummary[]>(`/orders/audits?limit=${limit}`);
}

export async function getAutomationStatus(): Promise<ApiResult<AutomationStatusResponse>> {
  return readApiResult<AutomationStatusResponse>('/automation/status');
}

export async function getPaperLedger(limit = 100): Promise<ApiResult<PaperPositionSummary[]>> {
  return readApiResult<PaperPositionSummary[]>(`/paper/ledger?limit=${limit}`);
}

export async function getPaperLedgerSummary(): Promise<ApiResult<PaperLedgerSummary>> {
  return readApiResult<PaperLedgerSummary>('/paper/ledger/summary');
}

export async function getReconciliationReport(): Promise<ApiResult<ReconciliationReportResponse>> {
  const adminToken = process.env.SCANNER_ADMIN_API_TOKEN;
  const headers: HeadersInit = adminToken
    ? { Authorization: `Bearer ${adminToken}` }
    : {};
  try {
    return {
      data: await fetchScannerJson<ReconciliationReportResponse>('/paper/reconcile', { headers }),
      error: null,
    };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : 'Unknown request error.',
    };
  }
}
