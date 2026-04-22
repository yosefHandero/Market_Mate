import type { ProjectionResponse, ScanRun } from '@/lib/types';
import { fetchScannerJson } from '@/lib/scanner-api';

export type RankBuySimulationOutput =
  | { ok: true; result: ProjectionResponse }
  | { ok: false; error: string };

export function scoreBandFor(score: number): string {
  if (score >= 90) return '90-100';
  if (score >= 80) return '80-89';
  if (score >= 70) return '70-79';
  if (score >= 60) return '60-69';
  return '0-59';
}

export async function fetchTickerProjection(
  ticker: string,
  signal: 'BUY' | 'SELL',
  scoreBand: string,
): Promise<RankBuySimulationOutput> {
  try {
    const data = await fetchScannerJson<ProjectionResponse>(
      `/scan/projection/${encodeURIComponent(ticker)}?signal=${signal}&score_band=${encodeURIComponent(scoreBand)}`,
    );
    return { ok: true, result: data };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : 'Projection request failed.',
    };
  }
}

export async function fetchProjection(
  rank: number,
  scan: ScanRun | null | undefined,
): Promise<RankBuySimulationOutput> {
  if (!scan?.results?.length) {
    return { ok: false, error: 'No scan results available.' };
  }

  if (!Number.isInteger(rank) || rank < 1 || rank > scan.results.length) {
    return {
      ok: false,
      error: `Rank must be an integer between 1 and ${scan.results.length}.`,
    };
  }

  const row = scan.results[rank - 1];
  const signal = row.decision_signal === 'SELL' ? 'SELL' : 'BUY';
  const band = scoreBandFor(row.raw_score ?? row.score ?? 0);

  return fetchTickerProjection(row.ticker, signal, band);
}
