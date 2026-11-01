'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { DecisionCard } from '@/components/decision-card';
import { buildDecisionWarning, VISIBLE_CANDIDATE_LIMIT } from '@/lib/decision-surface';
import { FRESH_BAR_MAX_MINUTES, hasBadFreshnessFlags } from '@/lib/freshness';
import { evaluatePaperActionGate } from '@/lib/paper-order';
import type { AutomationStatusResponse, DecisionRow, ScanResult } from '@/lib/types';

function isProductionSurfaceRow(row: { decision_role?: string | null }): boolean {
  const role = String(row.decision_role ?? 'production').trim().toLowerCase();
  return role !== 'shadow';
}

function isBuyCandidate(row: ScanResult): boolean {
  return row.decision_signal === 'BUY' && row.is_buy_candidate === true;
}

function rowProviderCritical(row: ScanResult): boolean {
  const status = String(row.provider_status ?? '').trim().toLowerCase();
  return status === 'critical' || status === 'error';
}

function rowBarsAreStale(row: ScanResult): boolean {
  const age = row.bar_age_minutes;
  return typeof age !== 'number' || !Number.isFinite(age) || age > FRESH_BAR_MAX_MINUTES;
}

function rowHasContextQualityWarning(row: ScanResult): boolean {
  return rowProviderCritical(row) || hasBadFreshnessFlags(row.freshness_flags);
}

function officialTopPicks(
  results: ScanResult[],
  topFromRun: ScanResult[] | undefined,
  assetType: 'stock' | 'crypto',
): ScanResult[] {
  const source = topFromRun?.length
    ? topFromRun
    : results
        .filter((row) => row.asset_type === assetType && row.is_top_pick)
        .sort((left, right) => (left.selection_rank ?? 999) - (right.selection_rank ?? 999));

  return source.filter((row) => isProductionSurfaceRow(row) && isBuyCandidate(row));
}

function candidateKey(row: ScanResult): string {
  return `${row.asset_type}:${row.ticker}`;
}

function paperActionAllowed(
  result: ScanResult,
  decision: DecisionRow | null | undefined,
  automation: AutomationStatusResponse | null | undefined,
): boolean {
  return evaluatePaperActionGate({ result, decision, automation }).allowed;
}

const HELD_BACK_PREVIEW_LIMIT = 3;

function heldBackReason(
  result: ScanResult,
  decision: DecisionRow | null | undefined,
  automation: AutomationStatusResponse | null | undefined,
): string {
  // Prefer the scanner's own verdict so the Decision page and Proof agree.
  const readiness = String(result.readiness_reason ?? '').trim();
  if (readiness && !/^actionable/i.test(readiness)) return readiness;
  const gate = String(result.gate_reason ?? '').trim();
  if (result.gate_passed === false && gate) return gate;
  return evaluatePaperActionGate({ result, decision, automation }).reason;
}

function describeSignalMix(rows: ScanResult[]): string {
  const counts = rows.reduce(
    (acc, row) => {
      const key = row.decision_signal === 'SELL' ? 'sell' : 'hold';
      acc[key] += 1;
      return acc;
    },
    { hold: 0, sell: 0 },
  );
  const parts: string[] = [];
  if (counts.hold) parts.push(`${counts.hold} HOLD`);
  if (counts.sell) parts.push(`${counts.sell} SELL`);
  return parts.length ? ` The latest scan produced no BUY signals (${parts.join(', ')}).` : '';
}

function CandidateColumn({
  label,
  ariaLabel,
  emptyTestId,
  emptyText,
  gridTestId,
  picks,
  decisionsBySymbol,
  automation,
}: {
  label: string;
  ariaLabel: string;
  emptyTestId: string;
  emptyText: string;
  gridTestId: string;
  picks: ScanResult[];
  decisionsBySymbol: Map<string, DecisionRow>;
  automation?: AutomationStatusResponse | null;
}) {
  return (
    <section className="decision-column" role="region" aria-label={ariaLabel}>
      <h2 className="decision-column-heading">{label}</h2>
      {picks.length ? (
        <div className="candidate-list" data-testid={gridTestId}>
          {picks.map((result) => (
            <DecisionCard
              key={result.ticker}
              result={result}
              decision={decisionsBySymbol.get(result.ticker) ?? null}
              automation={automation}
            />
          ))}
        </div>
      ) : (
        <p className="muted decision-column-empty" data-testid={emptyTestId}>
          {emptyText}
        </p>
      )}
    </section>
  );
}

export function DecisionGrid({
  results,
  topStocks,
  topCrypto,
  decisions,
  automation,
  decisionsError,
  scanStale = false,
  coverageIncomplete = false,
}: {
  results: ScanResult[];
  topStocks?: ScanResult[];
  topCrypto?: ScanResult[];
  decisions: DecisionRow[];
  automation?: AutomationStatusResponse | null;
  decisionsError?: string | null;
  scanStale?: boolean;
  coverageIncomplete?: boolean;
}) {
  const productionResults = useMemo(
    () => results.filter(isProductionSurfaceRow),
    [results],
  );
  const decisionsBySymbol = useMemo(
    () =>
      new Map(
        decisions
          .filter(isProductionSurfaceRow)
          .map((row) => [row.symbol, row]),
      ),
    [decisions],
  );

  const officialStockPicks = useMemo(
    () => officialTopPicks(productionResults, topStocks, 'stock'),
    [productionResults, topStocks],
  );
  const officialCryptoPicks = useMemo(
    () => officialTopPicks(productionResults, topCrypto, 'crypto'),
    [productionResults, topCrypto],
  );
  const stockQualified = useMemo(
    () =>
      officialStockPicks.filter((row) =>
        paperActionAllowed(row, decisionsBySymbol.get(row.ticker), automation),
      ),
    [automation, decisionsBySymbol, officialStockPicks],
  );
  const cryptoQualified = useMemo(
    () =>
      officialCryptoPicks.filter((row) =>
        paperActionAllowed(row, decisionsBySymbol.get(row.ticker), automation),
      ),
    [automation, decisionsBySymbol, officialCryptoPicks],
  );
  const stockPicks = stockQualified.slice(0, VISIBLE_CANDIDATE_LIMIT);
  const cryptoPicks = cryptoQualified.slice(0, VISIBLE_CANDIDATE_LIMIT);
  const displayedPicks = useMemo(() => [...stockPicks, ...cryptoPicks], [cryptoPicks, stockPicks]);
  // BUY signals the scanner produced but that did not clear the paper-action
  // gate. These explain an empty list and are the only non-displayed rows whose
  // data quality is worth flagging here.
  const heldBack = useMemo(() => {
    const shown = new Set(displayedPicks.map(candidateKey));
    const seen = new Set<string>();
    return [...officialStockPicks, ...officialCryptoPicks, ...productionResults].filter((row) => {
      const key = candidateKey(row);
      if (row.decision_signal !== 'BUY' || shown.has(key) || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [displayedPicks, officialCryptoPicks, officialStockPicks, productionResults]);
  const heldBackCount = heldBack.length;
  const bothEmpty = displayedPicks.length === 0;
  // Data-quality warnings describe what the reader is looking at: the displayed
  // picks, or, when the list is empty, the held-back setups (or the whole scan
  // when there were no BUY signals at all).
  const warningScope = displayedPicks.length
    ? displayedPicks
    : heldBack.length
      ? heldBack
      : productionResults;
  const barsStale = warningScope.some((row) => rowBarsAreStale(row));
  const marketDataDegraded = warningScope.some((row) => rowHasContextQualityWarning(row));
  const warning = buildDecisionWarning({
    killSwitchOn: automation?.kill_switch_enabled === true,
    breakerOpen: automation?.breaker?.state === 'open',
    scanStale,
    barsStale,
    coverageIncomplete,
    marketDataDegraded,
    heldBackCount,
  });
  const emptyMessage = productionResults.length
    ? 'No qualifying buy candidates in the latest scan.'
    : 'No scan results yet.';
  const heldBackPreview = heldBack.slice(0, HELD_BACK_PREVIEW_LIMIT);
  const heldBackOverflow = heldBack.length - heldBackPreview.length;

  return (
    <div className="decision-grid" data-testid="decision-grid">
      {decisionsError ? (
        <p className="negative decision-load-error" role="alert">
          {decisionsError}
        </p>
      ) : null}

      {warning && !bothEmpty ? (
        <p
          className={`decision-warning${warning.tone === 'safety' ? ' decision-warning-safety' : ''}`}
          role="status"
          data-testid="decision-data-warning"
        >
          {warning.message}
        </p>
      ) : null}

      {bothEmpty ? (
        <div className="decision-empty" data-testid="decision-empty-state">
          <p style={{ margin: 0 }}>
            {emptyMessage}
            {productionResults.length > 0 && heldBack.length === 0
              ? describeSignalMix(productionResults)
              : null}{' '}
            {warning ? <span data-testid="decision-data-warning">{warning.message} </span> : null}
            <Link href="/proof" data-testid="decision-proof-link">
              See Proof
            </Link>{' '}
            for coverage and evidence.
          </p>
          {heldBackPreview.length ? (
            <div className="decision-held-back" data-testid="decision-held-back">
              <p className="muted small" style={{ margin: '8px 0 4px' }}>
                {heldBack.length === 1
                  ? '1 BUY signal was held back:'
                  : `${heldBack.length} BUY signals were held back:`}
              </p>
              <ul className="decision-reason-list small">
                {heldBackPreview.map((row) => (
                  <li key={candidateKey(row)} data-testid={`held-back-${row.ticker}`}>
                    <strong>{row.ticker}</strong>{' '}
                    <span className="muted">
                      {heldBackReason(row, decisionsBySymbol.get(row.ticker), automation)}
                    </span>
                  </li>
                ))}
              </ul>
              {heldBackOverflow > 0 ? (
                <p className="muted small" style={{ margin: '4px 0 0' }}>
                  +{heldBackOverflow} more on Proof.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="decision-columns">
          <CandidateColumn
            label="Stocks"
            ariaLabel="Stock buy candidates"
            emptyTestId="stock-empty-state"
            emptyText="No qualifying stocks."
            gridTestId="stock-actionable-grid"
            picks={stockPicks}
            decisionsBySymbol={decisionsBySymbol}
            automation={automation}
          />
          <CandidateColumn
            label="Crypto"
            ariaLabel="Crypto buy candidates"
            emptyTestId="crypto-empty-state"
            emptyText="No qualifying crypto."
            gridTestId="crypto-actionable-grid"
            picks={cryptoPicks}
            decisionsBySymbol={decisionsBySymbol}
            automation={automation}
          />
        </div>
      )}
    </div>
  );
}
