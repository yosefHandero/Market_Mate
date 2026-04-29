'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { createJournalEntry } from '@/lib/api';
import type { JournalDecision } from '@/lib/types';

const decisions: JournalDecision[] = ['watching', 'took', 'skipped'];

type JournalEntryFormProps = {
  defaultTicker?: string;
  defaultEntryPrice?: number | null;
  defaultRunId?: string | null;
  defaultSignalLabel?: string | null;
  defaultScore?: number | null;
  defaultNewsSource?: string | null;
};

export function JournalEntryForm({
  defaultTicker = '',
  defaultEntryPrice = null,
  defaultRunId = null,
  defaultSignalLabel = null,
  defaultScore = null,
  defaultNewsSource = null,
}: JournalEntryFormProps) {
  const [ticker, setTicker] = useState(defaultTicker);
  const [runId, setRunId] = useState(defaultRunId ?? '');
  const [decision, setDecision] = useState<JournalDecision>('watching');
  const [entryPrice, setEntryPrice] = useState(
    defaultEntryPrice != null ? String(defaultEntryPrice) : '',
  );
  const [exitPrice, setExitPrice] = useState('');
  const [notes, setNotes] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [messageTone, setMessageTone] = useState<'success' | 'error' | null>(null);
  const router = useRouter();
  const pnlPct = (() => {
    if (!entryPrice || !exitPrice) return null;
    const parsedEntry = Number(entryPrice);
    const parsedExit = Number(exitPrice);
    if (!Number.isFinite(parsedEntry) || !Number.isFinite(parsedExit) || parsedEntry <= 0) {
      return null;
    }
    return ((parsedExit - parsedEntry) / parsedEntry) * 100;
  })();

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const normalizedTicker = ticker.trim().toUpperCase();
    const parsedEntryPrice = entryPrice ? Number(entryPrice) : null;
    const parsedExitPrice = exitPrice ? Number(exitPrice) : null;

    if (!normalizedTicker) {
      setMessage('Ticker is required.');
      setMessageTone('error');
      return;
    }

    if (parsedEntryPrice != null && (!Number.isFinite(parsedEntryPrice) || parsedEntryPrice <= 0)) {
      setMessage('Entry price must be a valid positive number.');
      setMessageTone('error');
      return;
    }

    if (parsedExitPrice != null && (!Number.isFinite(parsedExitPrice) || parsedExitPrice <= 0)) {
      setMessage('Exit price must be a valid positive number.');
      setMessageTone('error');
      return;
    }

    if (parsedExitPrice != null && parsedEntryPrice == null) {
      setMessage('Exit price requires an entry price.');
      setMessageTone('error');
      return;
    }

    setSaving(true);
    setMessage('');
    setMessageTone(null);

    try {
      await createJournalEntry({
        ticker: normalizedTicker,
        run_id: runId.trim() || null,
        decision,
        entry_price: parsedEntryPrice,
        exit_price: parsedExitPrice,
        pnl_pct: pnlPct,
        signal_label: defaultSignalLabel,
        score: defaultScore,
        news_source: defaultNewsSource,
        notes: notes.trim(),
        override_reason: overrideReason.trim() || null,
        action_state: decision,
      });

      router.refresh();

      setTicker(defaultTicker);
      setRunId(defaultRunId ?? '');
      setDecision('watching');
      setEntryPrice(defaultEntryPrice != null ? String(defaultEntryPrice) : '');
      setExitPrice('');
      setNotes('');
      setOverrideReason('');
      setMessage('Journal entry saved.');
      setMessageTone('success');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save journal entry.');
      setMessageTone('error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="journal-form" onSubmit={onSubmit}>
      <div className="form-grid">
        <div>
          <label className="form-label" htmlFor="journal-ticker">
            Ticker
          </label>
          <input
            id="journal-ticker"
            className="input"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            maxLength={16}
            required
          />
        </div>

        <div>
          <label className="form-label" htmlFor="journal-decision">
            Decision
          </label>
          <select
            id="journal-decision"
            className="input"
            value={decision}
            onChange={(e) => setDecision(e.target.value as JournalDecision)}
          >
            {decisions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="form-label" htmlFor="journal-run-id">
          Linked run ID
        </label>
        <input
          id="journal-run-id"
          className="input"
          value={runId}
          onChange={(e) => setRunId(e.target.value)}
          placeholder="Latest scan run id"
        />
        <div className="small muted" style={{ marginTop: 6 }}>
          Override this if the journal entry belongs to an older scan. Traceability is better when
          the run ID matches the original signal.
        </div>
      </div>

      <div className="form-grid">
        <div>
          <label className="form-label" htmlFor="journal-entry-price">
            Entry price (optional)
          </label>
          <input
            id="journal-entry-price"
            className="input"
            type="number"
            step="0.01"
            min="0"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            placeholder="260.81"
          />
        </div>

        <div>
          <label className="form-label" htmlFor="journal-exit-price">
            Exit price (optional)
          </label>
          <input
            id="journal-exit-price"
            className="input"
            type="number"
            step="0.01"
            min="0"
            value={exitPrice}
            onChange={(e) => setExitPrice(e.target.value)}
            placeholder="265.40"
          />
        </div>
      </div>
      {pnlPct != null ? (
        <div className={`small ${pnlPct >= 0 ? 'positive' : 'negative'}`}>
          Estimated P/L: {pnlPct >= 0 ? '+' : ''}
          {pnlPct.toFixed(2)}%
        </div>
      ) : null}
      <div className="small muted">
        Signal: {defaultSignalLabel ?? '—'}
        {' • '}
        Score: {defaultScore != null ? defaultScore.toFixed(1) : '—'}
        {' • '}
        News: {defaultNewsSource ?? '—'}
      </div>

      <div>
        <label className="form-label" htmlFor="journal-override-reason">
          Override reason (optional)
        </label>
        <input
          id="journal-override-reason"
          className="input"
          value={overrideReason}
          onChange={(e) => setOverrideReason(e.target.value)}
          placeholder="Why you overrode the default path..."
          maxLength={200}
        />
      </div>

      <div>
        <label className="form-label" htmlFor="journal-notes">
          Notes
        </label>
        <textarea
          id="journal-notes"
          className="textarea"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Why you took it, skipped it, or are still watching it..."
          rows={4}
        />
      </div>

      <div className="form-actions">
        <button className="button" type="submit" disabled={saving}>
          {saving ? 'Saving...' : 'Save journal entry'}
        </button>
        {message ? (
          <span
            className={`small ${messageTone === 'error' ? 'negative' : messageTone === 'success' ? 'positive' : 'muted'}`}
            aria-live="polite"
          >
            {message}
          </span>
        ) : null}
      </div>
    </form>
  );
}
