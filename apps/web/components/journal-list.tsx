'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { JournalDecision, JournalEntry } from '@/lib/types';
import { updateJournalEntry } from '@/lib/api';
import { JournalSummary } from '@/components/journal-summary';
import { JournalEntryCard } from '@/components/journal-entry-card';
import { JournalFilterBar } from '@/components/journal-filter-bar';

export function JournalList({ entries }: { entries: JournalEntry[] }) {
  const [filter, setFilter] = useState<'all' | JournalDecision>('all');
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const router = useRouter();

  const filteredEntries = useMemo(() => {
    const base = filter === 'all' ? entries : entries.filter((entry) => entry.decision === filter);

    return [...base].sort((a, b) => {
      const aOpen = a.decision === 'took' && a.exit_price == null ? 1 : 0;
      const bOpen = b.decision === 'took' && b.exit_price == null ? 1 : 0;

      if (aOpen !== bOpen) return bOpen - aOpen;

      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [entries, filter]);

  async function handleDecisionUpdate(entry: JournalEntry, decision: 'took' | 'skipped') {
    const confirmText =
      decision === 'took' ? `Mark ${entry.ticker} as took?` : `Mark ${entry.ticker} as skipped?`;

    if (!window.confirm(confirmText)) return;

    try {
      setErrorMessage('');
      setUpdatingId(entry.id);

      await updateJournalEntry(entry.id, {
        decision,
        entry_price: entry.entry_price,
        exit_price: entry.exit_price,
        pnl_pct: entry.pnl_pct,
        notes: entry.notes ?? '',
        override_reason: entry.override_reason ?? null,
        action_state: decision,
      });

      router.refresh();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : `Failed to update ${entry.ticker}.`);
    } finally {
      setUpdatingId(null);
    }
  }

  return (
    <div className="history-list">
      {errorMessage ? (
        <div className="small negative" style={{ marginBottom: 10 }}>
          {errorMessage}
        </div>
      ) : null}

      <JournalSummary entries={entries} />

      <JournalFilterBar filter={filter} onChange={setFilter} />

      {filteredEntries.length ? (
        filteredEntries.map((entry) => (
          <JournalEntryCard
            key={entry.id}
            entry={entry}
            isUpdating={updatingId === entry.id}
            onMarkAsTook={(item) => handleDecisionUpdate(item, 'took')}
            onMarkAsSkipped={(item) => handleDecisionUpdate(item, 'skipped')}
          />
        ))
      ) : (
        <p className="muted small">No journal entries for this filter.</p>
      )}
    </div>
  );
}
