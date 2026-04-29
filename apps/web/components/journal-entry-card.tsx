'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { JournalEntry } from '@/lib/types';
import { updateJournalEntry } from '@/lib/api';
import { JournalEntryActions } from '@/components/journal-entry-actions';

function decisionBadgeClass(decision: string) {
  if (decision === 'took') return 'green';
  if (decision === 'skipped') return 'amber';
  return 'blue';
}

type JournalEntryCardProps = {
  entry: JournalEntry;
  isUpdating: boolean;
  onMarkAsTook: (entry: JournalEntry) => void;
  onMarkAsSkipped: (entry: JournalEntry) => void;
};

export function JournalEntryCard({
  entry,
  isUpdating,
  onMarkAsTook,
  onMarkAsSkipped,
}: JournalEntryCardProps) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [editEntryPrice, setEditEntryPrice] = useState(
    entry.entry_price != null ? String(entry.entry_price) : '',
  );
  const [editExitPrice, setEditExitPrice] = useState(
    entry.exit_price != null ? String(entry.exit_price) : '',
  );
  const [editNotes, setEditNotes] = useState(entry.notes ?? '');
  const [editOverrideReason, setEditOverrideReason] = useState(entry.override_reason ?? '');
  const [editError, setEditError] = useState('');

  const editPnlPct = useMemo(() => {
    if (!editEntryPrice || !editExitPrice) return null;

    const entryNum = Number(editEntryPrice);
    const exitNum = Number(editExitPrice);

    if (!Number.isFinite(entryNum) || !Number.isFinite(exitNum) || entryNum <= 0) {
      return null;
    }

    return ((exitNum - entryNum) / entryNum) * 100;
  }, [editEntryPrice, editExitPrice]);

  async function handleSaveEdit() {
    const parsedEntry = editEntryPrice ? Number(editEntryPrice) : null;
    const parsedExit = editExitPrice ? Number(editExitPrice) : null;

    if (parsedEntry != null && (!Number.isFinite(parsedEntry) || parsedEntry <= 0)) {
      setEditError('Entry price must be a valid positive number.');
      return;
    }

    if (parsedExit != null && (!Number.isFinite(parsedExit) || parsedExit <= 0)) {
      setEditError('Exit price must be a valid positive number.');
      return;
    }

    if (parsedExit != null && parsedEntry == null) {
      setEditError('Exit price requires an entry price.');
      return;
    }

    try {
      setEditError('');
      setIsSavingEdit(true);

      await updateJournalEntry(entry.id, {
        entry_price: parsedEntry,
        exit_price: parsedExit,
        pnl_pct: editPnlPct,
        notes: editNotes,
        override_reason: editOverrideReason || null,
        action_state: entry.decision,
      });

      setIsEditing(false);
      router.refresh();
    } catch (error) {
      setEditError(
        error instanceof Error ? error.message : `Failed to save changes for ${entry.ticker}.`,
      );
    } finally {
      setIsSavingEdit(false);
    }
  }

  function handleCancelEdit() {
    setEditEntryPrice(entry.entry_price != null ? String(entry.entry_price) : '');
    setEditExitPrice(entry.exit_price != null ? String(entry.exit_price) : '');
    setEditNotes(entry.notes ?? '');
    setEditOverrideReason(entry.override_reason ?? '');
    setEditError('');
    setIsEditing(false);
  }

  return (
    <div className="history-item">
      <div className="header-row">
        <div>
          <strong>{entry.ticker}</strong>
          <div className="muted small">{new Date(entry.created_at).toLocaleString()}</div>
          <div className="muted small">ID: {entry.id}</div>
        </div>
        <span className={`badge ${decisionBadgeClass(entry.decision)}`}>{entry.decision}</span>
      </div>

      {!isEditing ? (
        <>
          <div className="small" style={{ marginTop: 8 }}>
            Entry: {entry.entry_price != null ? `$${entry.entry_price.toFixed(2)}` : '—'}
            {' • '}
            Exit: {entry.exit_price != null ? `$${entry.exit_price.toFixed(2)}` : '—'}
            {' • '}
            <span
              className={
                entry.pnl_pct != null ? (entry.pnl_pct >= 0 ? 'positive' : 'negative') : ''
              }
            >
              P/L:{' '}
              {entry.pnl_pct != null
                ? `${entry.pnl_pct >= 0 ? '+' : ''}${entry.pnl_pct.toFixed(2)}%`
                : '—'}
            </span>
            <div className="small muted" style={{ marginTop: 8 }}>
              Signal: {entry.signal_label ?? '—'}
              {' • '}
              Score: {entry.score != null ? entry.score.toFixed(1) : '—'}
              {' • '}
              News: {entry.news_source ?? '—'}
            </div>
            <div className="small muted" style={{ marginTop: 6 }}>
              {entry.decision === 'watching'
                ? 'Status: waiting for decision'
                : entry.decision === 'took' && entry.exit_price == null
                  ? 'Status: trade open'
                  : entry.decision === 'took' && entry.exit_price != null
                    ? 'Status: trade closed'
                    : 'Status: skipped'}
            </div>
            {entry.override_reason ? (
              <div className="small muted" style={{ marginTop: 6 }}>
                Override reason: {entry.override_reason}
              </div>
            ) : null}
          </div>

          {entry.notes ? (
            <div className="muted small" style={{ marginTop: 8 }}>
              {entry.notes}
            </div>
          ) : null}

          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              type="button"
              className="button"
              onClick={() => setIsEditing(true)}
              disabled={isUpdating}
            >
              Edit
            </button>

            {entry.decision === 'took' && entry.exit_price == null ? (
              <button
                type="button"
                className="button"
                disabled={isUpdating}
                onClick={() => setIsEditing(true)}
              >
                Close trade
              </button>
            ) : null}
          </div>

          <JournalEntryActions
            entry={entry}
            isUpdating={isUpdating}
            onMarkAsTook={onMarkAsTook}
            onMarkAsSkipped={onMarkAsSkipped}
          />
        </>
      ) : (
        <div className="journal-form" style={{ marginTop: 10 }}>
          {entry.decision === 'took' && entry.exit_price == null ? (
            <div className="small muted">Add an exit price to close this trade.</div>
          ) : null}

          <div className="form-grid">
            <div>
              <label className="form-label" htmlFor={`journal-entry-price-${entry.id}`}>
                Entry price
              </label>
              <input
                id={`journal-entry-price-${entry.id}`}
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={editEntryPrice}
                onChange={(e) => setEditEntryPrice(e.target.value)}
                placeholder="Entry price"
              />
            </div>

            <div>
              <label className="form-label" htmlFor={`journal-exit-price-${entry.id}`}>
                Exit price
              </label>
              <input
                id={`journal-exit-price-${entry.id}`}
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={editExitPrice}
                onChange={(e) => setEditExitPrice(e.target.value)}
                placeholder="Exit price"
              />
            </div>
          </div>

          {editPnlPct != null ? (
            <div className={`small ${editPnlPct >= 0 ? 'positive' : 'negative'}`}>
              Estimated P/L: {editPnlPct >= 0 ? '+' : ''}
              {editPnlPct.toFixed(2)}%
            </div>
          ) : (
            <div className="small muted">Estimated P/L: —</div>
          )}

          <div>
            <label className="form-label" htmlFor={`journal-override-reason-${entry.id}`}>
              Override reason
            </label>
            <input
              id={`journal-override-reason-${entry.id}`}
              className="input"
              value={editOverrideReason}
              onChange={(e) => setEditOverrideReason(e.target.value)}
              placeholder="Why you overrode the default path..."
              maxLength={200}
            />
          </div>

          <div>
            <label className="form-label" htmlFor={`journal-notes-${entry.id}`}>
              Notes
            </label>
            <textarea
              id={`journal-notes-${entry.id}`}
              className="textarea"
              rows={4}
              value={editNotes}
              onChange={(e) => setEditNotes(e.target.value)}
              placeholder="Update your trade notes..."
            />
          </div>

          {editError ? <div className="small negative">{editError}</div> : null}

          <div className="form-actions">
            <button
              type="button"
              className="button blue"
              disabled={isSavingEdit}
              onClick={handleSaveEdit}
            >
              {isSavingEdit ? 'Saving...' : 'Save changes'}
            </button>

            <button
              type="button"
              className="button"
              disabled={isSavingEdit}
              onClick={handleCancelEdit}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
