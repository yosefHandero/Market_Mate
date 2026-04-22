'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { JournalEntryForm } from '@/components/journal-entry-form';
import { updateJournalEntry } from '@/lib/api';
import type { ActionItem } from '@/lib/types';

function PaperLoopDisabledCard({ item }: { item: ActionItem }) {
  return (
    <div className="history-item" style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div>
          <strong>{item.title}</strong>
          <div className="muted small" style={{ marginTop: 4 }}>{item.subtitle}</div>
        </div>
        <span className="badge amber">Disabled</span>
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>
        Set <code>PAPER_LOOP_ENABLED=true</code> and <code>PAPER_LOOP_PHASE=shadow</code> in your
        scanner <code>.env</code> file, then restart the scanner service.
      </div>
    </div>
  );
}

function KillSwitchCard({ item }: { item: ActionItem }) {
  return (
    <div className="history-item" style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div>
          <strong>{item.title}</strong>
          <div className="muted small" style={{ marginTop: 4 }}>{item.subtitle}</div>
        </div>
        <span className="badge red">Active</span>
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>
        Set <code>PAPER_LOOP_KILL_SWITCH=false</code> in your scanner <code>.env</code> file, then
        restart the scanner service.
      </div>
    </div>
  );
}

function BreakerOpenCard({ item }: { item: ActionItem }) {
  return (
    <div className="history-item" style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div>
          <strong>{item.title}</strong>
          <div className="muted small" style={{ marginTop: 4 }}>{item.subtitle}</div>
        </div>
        <span className="badge red">Open</span>
      </div>
      {item.metadata.last_error ? (
        <div className="small negative" style={{ marginTop: 2 }}>
          Last error: {String(item.metadata.last_error)}
        </div>
      ) : null}
    </div>
  );
}

function SchedulerStoppedCard({ item }: { item: ActionItem }) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; tone: string } | null>(null);
  const router = useRouter();

  const handleStart = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetch('/api/scan/scheduler', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'start' }),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        setFeedback({ message: data.detail ?? `Failed (${res.status})`, tone: 'negative' });
        return;
      }
      setFeedback({ message: 'Scheduler started', tone: 'positive' });
      router.refresh();
    } catch {
      setFeedback({ message: 'Network error', tone: 'negative' });
    } finally {
      setBusy(false);
    }
  }, [router]);

  return (
    <div className="history-item" style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div>
          <strong>{item.title}</strong>
          <div className="muted small" style={{ marginTop: 4 }}>{item.subtitle}</div>
        </div>
        <button
          className="button"
          disabled={busy}
          onClick={handleStart}
          style={{ width: 'auto', padding: '8px 16px', whiteSpace: 'nowrap' }}
        >
          {busy ? 'Starting...' : 'Start scheduler'}
        </button>
      </div>
      {feedback ? (
        <span className={`small ${feedback.tone}`}>{feedback.message}</span>
      ) : null}
    </div>
  );
}

function ReviewSignalCard({ item }: { item: ActionItem }) {
  const m = item.metadata;
  return (
    <div className="history-item" style={{ display: 'grid', gap: 10 }}>
      <div>
        <strong>{item.title}</strong>
        <div className="muted small" style={{ marginTop: 4 }}>{item.subtitle}</div>
      </div>
      <JournalEntryForm
        defaultTicker={String(m.symbol ?? '')}
        defaultEntryPrice={typeof m.price === 'number' ? m.price : null}
        defaultRunId={typeof m.run_id === 'string' ? m.run_id : null}
        defaultSignalLabel={typeof m.signal_label === 'string' ? m.signal_label : null}
        defaultScore={typeof m.score === 'number' ? m.score : null}
        defaultNewsSource={typeof m.news_source === 'string' ? m.news_source : null}
      />
    </div>
  );
}

function WatchingEntryCard({ item }: { item: ActionItem }) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; tone: string } | null>(null);
  const router = useRouter();
  const entryId = item.metadata.entry_id as number;

  const handleDecision = useCallback(
    async (decision: 'took' | 'skipped') => {
      if (!window.confirm(`Mark ${item.metadata.ticker} as ${decision}?`)) return;
      setBusy(true);
      try {
        await updateJournalEntry(entryId, {
          decision,
          action_state: decision,
        });
        setFeedback({ message: `Marked as ${decision}`, tone: 'positive' });
        router.refresh();
      } catch (error) {
        setFeedback({
          message: error instanceof Error ? error.message : 'Update failed',
          tone: 'negative',
        });
      } finally {
        setBusy(false);
      }
    },
    [entryId, item.metadata.ticker, router],
  );

  return (
    <div className="history-item" style={{ display: 'grid', gap: 8 }}>
      <div>
        <strong>{item.title}</strong>
        <div className="muted small" style={{ marginTop: 4 }}>{item.subtitle}</div>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button
          className="button blue"
          disabled={busy}
          onClick={() => handleDecision('took')}
          style={{ width: 'auto', padding: '8px 16px' }}
        >
          {busy ? 'Updating...' : 'Mark as took'}
        </button>
        <button
          className="button amber"
          disabled={busy}
          onClick={() => handleDecision('skipped')}
          style={{ width: 'auto', padding: '8px 16px' }}
        >
          {busy ? 'Updating...' : 'Mark as skipped'}
        </button>
      </div>
      {feedback ? (
        <span className={`small ${feedback.tone}`}>{feedback.message}</span>
      ) : null}
    </div>
  );
}

const CARD_COMPONENTS: Record<string, React.ComponentType<{ item: ActionItem }>> = {
  paper_loop_disabled: PaperLoopDisabledCard,
  kill_switch_active: KillSwitchCard,
  breaker_open: BreakerOpenCard,
  scheduler_stopped: SchedulerStoppedCard,
  review_signal: ReviewSignalCard,
  watching_entry: WatchingEntryCard,
};

export function ActionList({ items }: { items: ActionItem[] }) {
  if (!items.length) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px' }}>
        <p className="muted">No actions required.</p>
        <p className="muted small" style={{ marginTop: 8 }}>
          All signals are processed and no configuration changes are needed.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => {
        const Card = CARD_COMPONENTS[item.type];
        if (!Card) return null;
        return <Card key={item.id} item={item} />;
      })}
    </div>
  );
}
