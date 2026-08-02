import {

  AutomationStatusResponse,

  DecisionRow,

  ExecutionAuditSummary,

  HealthResponse,

  PaperLedgerSummary,

  PaperPositionSummary,

  ProofSummary,

  ReconciliationReportResponse,

  ScanRun,

  SystemReadinessResponse,

} from '@/lib/types';

import { fetchScannerJson, readErrorMessage } from '@/lib/scanner-api';



export type ApiResult<T> = {

  data: T | null;

  error: string | null;

};



async function readApiResult<T>(scannerPath: string): Promise<ApiResult<T>> {

  try {

    const data = await fetchScannerJson<T>(scannerPath);

    return {

      data,

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



export async function getLatestDecisions(limit = 20): Promise<ApiResult<DecisionRow[]>> {

  return readApiResult<DecisionRow[]>(`/dashboard/decisions/latest?limit=${limit}`);

}



export async function getReadyz(): Promise<ApiResult<HealthResponse>> {

  return readApiResult<HealthResponse>('/readyz');

}



export async function getSystemReadiness(): Promise<ApiResult<SystemReadinessResponse>> {

  return readApiResult<SystemReadinessResponse>('/system/readiness');

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



export async function getProofSummary(): Promise<ApiResult<ProofSummary>> {

  return readApiResult<ProofSummary>('/proof/summary');

}



export async function reconcilePaperLedger(): Promise<ReconciliationReportResponse> {

  const res = await fetch('/api/paper/reconcile', {

    method: 'POST',

    cache: 'no-store',

  });



  if (!res.ok) {

    throw new Error(await readErrorMessage(res));

  }


  return (await res.json()) as ReconciliationReportResponse;
}
