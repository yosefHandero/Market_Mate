'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PaperLedgerPanel } from '@/components/paper-ledger-panel';
import { PaperTradingLoop } from '@/components/paper-trading-loop';
import { RankTable } from '@/components/rank-table';
import { getPaperLedger, getPaperLedgerSummary } from '@/lib/trading-desk';
import type {
  DecisionRow,
  PaperLedgerSummary,
  PaperPositionSummary,
  ScanRun,
} from '@/lib/types';

const EMPTY_RESULTS: ScanRun['results'] = [];

function buildLatestPriceMap(latestScan: ScanRun | null): Record<string, number> {
  return Object.fromEntries(
    (latestScan?.results ?? []).flatMap((row) => [
      [`${row.asset_type.toUpperCase()}:${row.ticker}`, row.price],
      [row.ticker, row.price],
    ]),
  );
}

export function TradingWorkspace({
  decisions,
  decisionsError,
  latestScan,
  initialPaperPositions,
  initialPaperSummary,
  paperLedgerError,
}: {
  decisions: DecisionRow[];
  decisionsError?: string | null;
  latestScan: ScanRun | null;
  initialPaperPositions: PaperPositionSummary[];
  initialPaperSummary: PaperLedgerSummary | null;
  paperLedgerError?: string | null;
}) {
  const rankedResults = latestScan?.results ?? EMPTY_RESULTS;
  const [activeTicker, setActiveTicker] = useState(rankedResults[0]?.ticker ?? '');
  const [paperPositions, setPaperPositions] = useState(initialPaperPositions);
  const [paperSummary, setPaperSummary] = useState(initialPaperSummary);
  const [ledgerError, setLedgerError] = useState<string | null>(paperLedgerError ?? null);
  const [refreshing, setRefreshing] = useState(false);
  const [highlightAuditId, setHighlightAuditId] = useState<number | null>(null);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const selectedResult =
    rankedResults.find((result) => result.ticker === activeTicker) ?? rankedResults[0] ?? null;
  const selectedDecision =
    decisions.find((decision) => decision.symbol === selectedResult?.ticker) ?? null;
  const latestPrices = useMemo(() => buildLatestPriceMap(latestScan), [latestScan]);

  const refreshLedger = useCallback(async (auditId?: number | null) => {
    setRefreshing(true);
    setLedgerError(null);
    try {
      const [positions, summary] = await Promise.all([
        getPaperLedger({ limit: 100 }),
        getPaperLedgerSummary(),
      ]);
      setPaperPositions(positions);
      setPaperSummary(summary);
      if (auditId != null) {
        setHighlightAuditId(auditId);
        if (highlightTimerRef.current) {
          clearTimeout(highlightTimerRef.current);
        }
        highlightTimerRef.current = setTimeout(() => {
          setHighlightAuditId(null);
          highlightTimerRef.current = null;
        }, 6000);
      }
    } catch (error) {
      setLedgerError(error instanceof Error ? error.message : 'Unable to refresh paper ledger.');
    } finally {
      setRefreshing(false);
    }
  }, []);

  const handleManualRefresh = useCallback(() => {
    void refreshLedger();
  }, [refreshLedger]);

  useEffect(
    () => () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
      }
    },
    [],
  );

  return (
    <div className="trading-workspace">
      <section className="card desk-shell">
        <div className="desk-card-header">
          <div>
            <h2 style={{ marginBottom: 8 }}>Dry-Run Paper Trading</h2>
            <p className="muted" style={{ margin: 0 }}>
              Select a ranked opportunity, preview it, place a paper dry-run, and verify ledger
              performance.
            </p>
          </div>
        </div>

        {decisionsError ? (
          <p className="negative small" style={{ marginTop: 12 }}>
            {decisionsError}
          </p>
        ) : null}

        <div className="desk-layout" style={{ marginTop: 16 }}>
          <section className="desk-watchlist-card">
            <div className="desk-card-header">
              <h3 style={{ margin: 0 }}>Ranked Opportunities</h3>
              <span className="muted small">Choose a ticker to preview</span>
            </div>
            {rankedResults.length ? (
              <RankTable
                results={rankedResults}
                topN={8}
                activeTicker={selectedResult?.ticker}
                onSelectTicker={setActiveTicker}
              />
            ) : (
              <p className="muted" style={{ margin: 0 }}>
                No ranked opportunities are available yet.
              </p>
            )}
          </section>

          <PaperTradingLoop
            selectedResult={selectedResult}
            selectedDecision={selectedDecision}
            onPaperOrderPlaced={refreshLedger}
          />
        </div>
      </section>

      <PaperLedgerPanel
        positions={paperPositions}
        summary={paperSummary}
        errorMessage={ledgerError}
        latestPrices={latestPrices}
        highlightAuditId={highlightAuditId}
        refreshing={refreshing}
        onRefresh={handleManualRefresh}
      />
    </div>
  );
}
