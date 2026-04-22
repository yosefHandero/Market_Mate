'use client';

import { useState, useCallback } from 'react';

interface FeedbackState {
  message: string;
  tone: 'positive' | 'negative' | 'muted';
}

export function OperatorActions({ schedulerRunning: _schedulerRunning }: { schedulerRunning: boolean }) {
  const [scanBusy, setScanBusy] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const showFeedback = useCallback((message: string, tone: FeedbackState['tone']) => {
    setFeedback({ message, tone });
    const id = setTimeout(() => setFeedback(null), 3000);
    return () => clearTimeout(id);
  }, []);

  const handleScan = useCallback(async () => {
    setScanBusy(true);
    try {
      const res = await fetch('/api/scan/run', { method: 'POST' });
      if (res.status === 503) {
        setUnavailable(true);
        showFeedback('Admin controls unavailable', 'muted');
        return;
      }
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        showFeedback(data.detail ?? `Scan failed (${res.status})`, 'negative');
        return;
      }
      const run = (await res.json()) as { scan_count?: number };
      showFeedback(`Scan completed: ${run.scan_count ?? 0} results`, 'positive');
    } catch {
      showFeedback('Network error triggering scan', 'negative');
    } finally {
      setScanBusy(false);
    }
  }, [showFeedback]);

  if (unavailable) {
    return <p className="muted small" style={{ marginBottom: 12 }}>Admin controls unavailable.</p>;
  }

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
      <button
        className="button"
        disabled={scanBusy}
        onClick={handleScan}
        style={{ width: 'auto', padding: '8px 16px' }}
      >
        {scanBusy ? 'Running...' : 'Run scan now'}
      </button>
      {feedback ? (
        <span className={`small ${feedback.tone}`}>{feedback.message}</span>
      ) : null}
    </div>
  );
}
