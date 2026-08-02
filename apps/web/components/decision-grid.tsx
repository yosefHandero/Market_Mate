'use client';

import { useMemo } from 'react';
import { DecisionCard } from '@/components/decision-card';
import { FRESH_BAR_MAX_MINUTES, hasBadFreshnessFlags } from '@/lib/freshness';
import type { AutomationStatusResponse, DecisionRow, ScanResult } from '@/lib/types';

function isBuyCandidate(row: ScanResult): boolean {
  // Never surface SELL/HOLD rows on the BUY-candidate product surface.
  if (row.decision_signal !== 'BUY') return false;
  if (row.is_buy_candidate != null) return row.is_buy_candidate === true;
  return true;
}

function rowProviderCritical(row: ScanResult): boolean {
  const status = String(row.provider_status ?? '').trim().toLowerCase();
  return status === 'critical' || status === 'error';
}

function rowStale(row: ScanResult): boolean {
  const age = row.bar_age_minutes;
  return (typeof age === 'number' && age > FRESH_BAR_MAX_MINUTES) || hasBadFreshnessFlags(row.freshness_flags);
}

function formatCount(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function reasonCount(count: number, reason: string): string | null {
  return count > 0 ? `${count} ${reason}` : null;
}

function rowConfidence(row: ScanResult): number | null {
  const value = row.confidence_score ?? row.calibrated_confidence ?? row.score;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function scarcityReasons(rows: ScanResult[], qualifiedVisibleCount: number): string[] {
  const buySignals = rows.filter((row) => row.decision_signal === 'BUY');
  const candidates = rows.filter(isBuyCandidate);
  const reasons = [
    reasonCount(
      Math.max(0, candidates.length - qualifiedVisibleCount),
      'qualified but ranked outside the visible top picks',
    ),
    reasonCount(rows.filter(rowProviderCritical).length, 'with provider data unavailable'),
    reasonCount(rows.filter(rowStale).length, 'with stale or insufficient fresh bars'),
    reasonCount(
      rows.filter((row) => row.readiness_hard_stop === true).length,
      'blocked by readiness hard-stops',
    ),
    reasonCount(
      rows.filter((row) => row.gate_passed === false && row.decision_signal === 'BUY').length,
      'BUY setup(s) rejected by trade gates',
    ),
    reasonCount(
      buySignals.filter((row) => row.is_buy_candidate === false).length,
      'BUY setup(s) below the candidate selector',
    ),
    reasonCount(
      rows.filter((row) => (row.evidence_grade ?? '').toLowerCase() === 'weak').length,
      'with weak evidence',
    ),
    reasonCount(
      rows.filter((row) => {
        const confidence = rowConfidence(row);
        return confidence != null && confidence < 50;
      }).length,
      'with low confidence',
    ),
  ].filter((reason): reason is string => Boolean(reason));

  if (!buySignals.length) {
    reasons.push('no qualifying BUY signal was present');
  }

  return [...new Set(reasons)].slice(0, 3);
}

function describeCandidateScarcity(
  rows: ScanResult[],
  label: 'stock' | 'crypto',
  qualifiedCount: number,
): string {
  const symbolSingular = label === 'crypto' ? 'crypto symbol' : 'stock symbol';
  const symbolPlural = label === 'crypto' ? 'crypto symbols' : 'stock symbols';
  if (!rows.length) {
    return `No ${symbolPlural} were scanned. Run a scan or check the ${label} universe configuration.`;
  }
  const candidates = rows.filter(isBuyCandidate);
  const heldBack = candidates.filter((row) => row.readiness_hard_stop === true);
  const staleCount = rows.filter(rowStale).length;
  const providerCritical = rows.filter(rowProviderCritical).length;

  if (candidates.length && heldBack.length === candidates.length) {
    const reason = heldBack[0]?.readiness_reason?.trim();
    const detail =
      reason && reason.length
        ? reason.replace(/^Hard stop:\s*/i, '')
        : staleCount === rows.length
          ? `market data is stale for all ${rows.length} ${label}s`
          : 'safety gates are active';
    return `${formatCount(candidates.length, `${label} buy candidate`)} held back: ${detail}. They reappear once fresh market data returns.`;
  }

  if (providerCritical === rows.length || staleCount === rows.length) {
    return `Market data for all ${formatCount(rows.length, symbolSingular, symbolPlural)} is stale or unavailable right now (provider critical or bars beyond ${FRESH_BAR_MAX_MINUTES}m). Candidates return when fresh data is available.`;
  }

  const opening =
    qualifiedCount === 0
      ? `No ${label} buy candidates qualified from ${formatCount(rows.length, symbolSingular, symbolPlural)}.`
      : `Only ${formatCount(qualifiedCount, `${label} buy candidate`)} qualified from ${formatCount(
          rows.length,
          symbolSingular,
          symbolPlural,
        )}.`;
  const reasons = scarcityReasons(rows, qualifiedCount);
  if (!reasons.length) {
    return `${opening} The remaining scanned symbols did not pass the BUY-candidate selector.`;
  }
  return `${opening} Likely blockers: ${reasons.join('; ')}.`;
}

function officialTopPicks(
  results: ScanResult[],
  topFromRun: ScanResult[] | undefined,
  assetType: 'stock' | 'crypto',
): ScanResult[] {
  const source =
    topFromRun?.length
      ? topFromRun
      : results
          .filter((row) => row.asset_type === assetType && row.is_top_pick)
          .sort((left, right) => (left.selection_rank ?? 999) - (right.selection_rank ?? 999));

  return source.filter(isBuyCandidate);
}

/**
 * When no executable picks exist (e.g. the market is closed and stock bars are stale),
 * still surface the last-session ranked buy candidates as READ-ONLY reference so the
 * product surface is not blank. These cards remain non-executable: each DecisionCard gates its
 * own Preview/Place on the backend hard-stop/eligibility, so nothing here bypasses safety.
 */
function referenceCandidates(results: ScanResult[], assetType: 'stock' | 'crypto'): ScanResult[] {
  return results
    .filter((row) => row.asset_type === assetType && isBuyCandidate(row))
    .sort((left, right) => {
      const rankLeft = left.selection_rank ?? 999;
      const rankRight = right.selection_rank ?? 999;
      if (rankLeft !== rankRight) return rankLeft - rankRight;
      return (right.upside_probability_pct ?? 0) - (left.upside_probability_pct ?? 0);
    })
    .slice(0, 5);
}

export function DecisionGrid({
  results,
  topStocks,
  topCrypto,
  decisions,
  automation,
  decisionsError,
}: {
  results: ScanResult[];
  topStocks?: ScanResult[];
  topCrypto?: ScanResult[];
  decisions: DecisionRow[];
  automation?: AutomationStatusResponse | null;
  decisionsError?: string | null;
}) {
  const decisionsBySymbol = useMemo(
    () => new Map(decisions.map((row) => [row.symbol, row])),
    [decisions],
  );

  const stockPicks = useMemo(
    () => officialTopPicks(results, topStocks, 'stock'),
    [results, topStocks],
  );
  const cryptoPicks = useMemo(
    () => officialTopPicks(results, topCrypto, 'crypto'),
    [results, topCrypto],
  );
  const stockShortfall = useMemo(
    () =>
      describeCandidateScarcity(
        results.filter((row) => row.asset_type === 'stock'),
        'stock',
        stockPicks.length,
      ),
    [results, stockPicks.length],
  );
  const cryptoShortfall = useMemo(
    () =>
      describeCandidateScarcity(
        results.filter((row) => row.asset_type === 'crypto'),
        'crypto',
        cryptoPicks.length,
      ),
    [results, cryptoPicks.length],
  );
  const stockReference = useMemo(
    () => (stockPicks.length ? [] : referenceCandidates(results, 'stock')),
    [stockPicks, results],
  );
  const cryptoReference = useMemo(
    () => (cryptoPicks.length ? [] : referenceCandidates(results, 'crypto')),
    [cryptoPicks, results],
  );

  return (
    <div className="decision-grid" data-testid="decision-grid">
      {decisionsError ? (
        <p className="negative small" role="alert">
          {decisionsError}
        </p>
      ) : null}

      <section className="decision-grid-section" role="region" aria-label="Top stock buy candidates">
        <h2 className="decision-grid-heading">Top Stock Buy Candidates</h2>
        {stockPicks.length ? (
          <>
            {stockPicks.length < 3 ? (
              <p className="muted small" role="status" data-testid="stock-sparse-state">
                {stockShortfall}
              </p>
            ) : null}
            <div className="decision-card-grid">
              {stockPicks.map((result) => (
                <DecisionCard
                  key={result.ticker}
                  result={result}
                  decision={decisionsBySymbol.get(result.ticker) ?? null}
                  automation={automation}
                />
              ))}
            </div>
          </>
        ) : stockReference.length ? (
          <>
            <p className="muted small" role="status" data-testid="stock-reference-note">
              Reference only - not executable right now. {stockShortfall}
            </p>
            <div className="decision-card-grid" data-testid="stock-reference-grid">
              {stockReference.map((result) => (
                <DecisionCard
                  key={result.ticker}
                  result={result}
                  decision={decisionsBySymbol.get(result.ticker) ?? null}
                  automation={automation}
                />
              ))}
            </div>
          </>
        ) : (
          <p className="muted" data-testid="stock-empty-state">
            {stockShortfall}
          </p>
        )}
      </section>

      <section className="decision-grid-section" role="region" aria-label="Top crypto buy candidates">
        <h2 className="decision-grid-heading">Top Crypto Buy Candidates</h2>
        {cryptoPicks.length ? (
          <>
            {cryptoPicks.length < 3 ? (
              <p className="muted small" role="status" data-testid="crypto-sparse-state">
                {cryptoShortfall}
              </p>
            ) : null}
            <div className="decision-card-grid">
              {cryptoPicks.map((result) => (
                <DecisionCard
                  key={result.ticker}
                  result={result}
                  decision={decisionsBySymbol.get(result.ticker) ?? null}
                  automation={automation}
                />
              ))}
            </div>
          </>
        ) : cryptoReference.length ? (
          <>
            <p className="muted small" role="status" data-testid="crypto-reference-note">
              Reference only - not executable right now. {cryptoShortfall}
            </p>
            <div className="decision-card-grid" data-testid="crypto-reference-grid">
              {cryptoReference.map((result) => (
                <DecisionCard
                  key={result.ticker}
                  result={result}
                  decision={decisionsBySymbol.get(result.ticker) ?? null}
                  automation={automation}
                />
              ))}
            </div>
          </>
        ) : (
          <p className="muted" data-testid="crypto-empty-state">
            {cryptoShortfall}
          </p>
        )}
      </section>
    </div>
  );
}
