import {
  DecisionRow,
  ExecutionAlignmentResponse,
  JournalAnalytics,
  JournalEntry,
  JournalEntryCreateRequest,
  JournalEntryUpdateRequest,
  ScanRun,
  ThresholdSweepResponse,
  ValidationSummary,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_SCANNER_API_BASE || "http://localhost:8005";

export type ApiResult<T> = {
  data: T | null;
  error: string | null;
};

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new Error(`Request returned invalid JSON for ${path}.`);
  }
}

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: string };
    if (typeof data.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    // Ignore JSON parse failures and fall back.
  }
  return `Request failed: ${res.status} ${res.statusText}`;
}

async function readApiResult<T>(path: string): Promise<ApiResult<T>> {
  try {
    return {
      data: await fetchJson<T>(path),
      error: null,
    };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : "Unknown request error.",
    };
  }
}

export async function getLatestScan(): Promise<ApiResult<ScanRun | null>> {
  return readApiResult<ScanRun | null>("/scan/latest");
}

export async function getScanHistory(limit = 12): Promise<ApiResult<ScanRun[]>> {
  return readApiResult<ScanRun[]>(`/scan/history?limit=${limit}`);
}
export async function getJournalEntries(limit = 50): Promise<ApiResult<JournalEntry[]>> {
  return readApiResult<JournalEntry[]>(`/journal/entries?limit=${limit}`);
}

export async function createJournalEntry(
  payload: JournalEntryCreateRequest
): Promise<JournalEntry> {
  const res = await fetch(`${API_BASE}/journal/entries`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  return (await res.json()) as JournalEntry;
}
export async function updateJournalEntry(
  entryId: number,
  payload: JournalEntryUpdateRequest
): Promise<JournalEntry> {
  const res = await fetch(`${API_BASE}/journal/entries/${entryId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  return (await res.json()) as JournalEntry;
}

export async function getJournalAnalytics(): Promise<ApiResult<JournalAnalytics>> {
  return readApiResult<JournalAnalytics>("/journal/analytics");
}

export async function getLatestDecisions(
  limit = 20,
): Promise<ApiResult<DecisionRow[]>> {
  return readApiResult<DecisionRow[]>(
    `/dashboard/decisions/latest?limit=${limit}`,
  );
}

export async function getValidationSummary(): Promise<ApiResult<ValidationSummary>> {
  return readApiResult<ValidationSummary>("/signals/validation/summary");
}

export async function getThresholdSweep(): Promise<ApiResult<ThresholdSweepResponse>> {
  return readApiResult<ThresholdSweepResponse>("/signals/validation/threshold-sweep");
}

export async function getExecutionAlignment(): Promise<ApiResult<ExecutionAlignmentResponse>> {
  return readApiResult<ExecutionAlignmentResponse>("/signals/validation/execution-alignment");
}