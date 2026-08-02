'use client';

import { useCallback, useState } from 'react';
import { PaperLedgerPanel } from '@/components/paper-ledger-panel';
import { getPaperLedger, getPaperLedgerSummary } from '@/lib/trading-desk';
import type { PaperLedgerSummary, PaperPositionSummary } from '@/lib/types';

export function ProofLedgerSection({
  initialPositions,
  initialSummary,
  initialError,
  latestPrices,
}: {
  initialPositions: PaperPositionSummary[];
  initialSummary: PaperLedgerSummary | null;
  initialError?: string | null;
  latestPrices: Record<string, number>;
}) {
  const [positions, setPositions] = useState(initialPositions);
  const [summary, setSummary] = useState(initialSummary);
  const [errorMessage, setErrorMessage] = useState<string | null>(initialError ?? null);
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    setErrorMessage(null);
    try {
      const [nextPositions, nextSummary] = await Promise.all([
        getPaperLedger({ limit: 100 }),
        getPaperLedgerSummary(),
      ]);
      setPositions(nextPositions);
      setSummary(nextSummary);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Unable to refresh paper ledger.');
    } finally {
      setRefreshing(false);
    }
  }, []);

  return (
    <PaperLedgerPanel
      positions={positions}
      summary={summary}
      errorMessage={errorMessage}
      latestPrices={latestPrices}
      refreshing={refreshing}
      onRefresh={() => void onRefresh()}
      defaultCollapsed={false}
    />
  );
}
