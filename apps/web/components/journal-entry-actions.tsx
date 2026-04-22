'use client';

import { JournalEntry } from '@/lib/types';

type JournalEntryActionsProps = {
  entry: JournalEntry;
  isUpdating: boolean;
  onMarkAsTook: (entry: JournalEntry) => void;
  onMarkAsSkipped: (entry: JournalEntry) => void;
};

export function JournalEntryActions({
  entry,
  isUpdating,
  onMarkAsTook,
  onMarkAsSkipped,
}: JournalEntryActionsProps) {
  const anyActionBusy = isUpdating;

  return (
    <>
      {entry.decision === 'watching' ? (
        <div
          style={{
            marginTop: 10,
            display: 'flex',
            gap: 8,
            flexWrap: 'wrap',
          }}
        >
          <button
            type="button"
            className="button blue"
            disabled={anyActionBusy}
            onClick={() => onMarkAsTook(entry)}
          >
            {isUpdating ? 'Updating...' : 'Mark as took'}
          </button>

          <button
            type="button"
            className="button amber"
            disabled={anyActionBusy}
            onClick={() => onMarkAsSkipped(entry)}
          >
            {isUpdating ? 'Updating...' : 'Mark as skipped'}
          </button>
        </div>
      ) : null}
    </>
  );
}
