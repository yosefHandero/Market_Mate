"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createJournalEntry } from "@/lib/api";
import { JournalDecision } from "@/lib/types";

const decisions: JournalDecision[] = ["watching", "took", "skipped"];

type JournalEntryFormProps = {
  defaultTicker?: string;
  defaultEntryPrice?: number | null;
  defaultRunId?: string | null;
  defaultSignalLabel?: string | null;
  defaultScore?: number | null;
  defaultNewsSource?: string | null;
};


export function JournalEntryForm({
  defaultTicker = "",
  defaultEntryPrice = null,
  defaultRunId = null,
  defaultSignalLabel = null,
  defaultScore = null,
  defaultNewsSource = null,
}: JournalEntryFormProps) {
  const [ticker, setTicker] = useState(defaultTicker);
  const [decision, setDecision] = useState<JournalDecision>("watching");
  const [entryPrice, setEntryPrice] = useState(
    defaultEntryPrice != null ? String(defaultEntryPrice) : "",
  );
  const [exitPrice, setExitPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const router = useRouter();
  const pnlPct = (() => {
    if (!entryPrice || !exitPrice) return null;
    const parsedEntry = Number(entryPrice);
    const parsedExit = Number(exitPrice);
    if (
      !Number.isFinite(parsedEntry) ||
      !Number.isFinite(parsedExit) ||
      parsedEntry <= 0
    ) {
      return null;
    }
    return ((parsedExit - parsedEntry) / parsedEntry) * 100;
  })();

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    setMessage("");

    try {
      await createJournalEntry({
        ticker: ticker.trim().toUpperCase(),
        run_id: defaultRunId,
        decision,
        entry_price: entryPrice ? Number(entryPrice) : null,
        exit_price: exitPrice ? Number(exitPrice) : null,
        pnl_pct: pnlPct,
        signal_label: defaultSignalLabel,
        score: defaultScore,
        news_source: defaultNewsSource,
        notes: notes.trim(),
      });

      router.refresh();

      setTicker(defaultTicker);
      setDecision("watching");
      setEntryPrice(defaultEntryPrice != null ? String(defaultEntryPrice) : "");
      setExitPrice("");
      setNotes("");
      setMessage("Journal entry saved.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Failed to save journal entry.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="journal-form" onSubmit={onSubmit}>
      <div className="form-grid">
        <div>
          <label className="form-label">Ticker</label>
          <input
            className="input"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            maxLength={16}
            required
          />
        </div>

        <div>
          <label className="form-label">Decision</label>
          <select
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

      <div className="form-grid">
        <div>
          <label className="form-label">Entry price (optional)</label>
          <input
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
          <label className="form-label">Exit price (optional)</label>
          <input
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
        <div className={`small ${pnlPct >= 0 ? "positive" : "negative"}`}>
          Estimated P/L: {pnlPct >= 0 ? "+" : ""}
          {pnlPct.toFixed(2)}%
        </div>
      ) : null}
      <div className="small muted">
        Signal: {defaultSignalLabel ?? "—"}
        {" • "}
        Score: {defaultScore != null ? defaultScore.toFixed(1) : "—"}
        {" • "}
        News: {defaultNewsSource ?? "—"}
      </div>

      <div>
        <label className="form-label">Notes</label>
        <textarea
          className="textarea"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Why you took it, skipped it, or are still watching it..."
          rows={4}
        />
      </div>

      <div className="form-actions">
        <button className="button" type="submit" disabled={saving}>
          {saving ? "Saving..." : "Save journal entry"}
        </button>
        {message ? <span className="muted small">{message}</span> : null}
      </div>
    </form>
  );
}
