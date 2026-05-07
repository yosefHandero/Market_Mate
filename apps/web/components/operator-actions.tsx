'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { readErrorMessage } from '@/lib/scanner-api';
import type { HealthResponse } from '@/lib/types';

interface FeedbackState {
  message: string;
  tone: 'positive' | 'negative' | 'muted';
}

interface SchedulerSnapshot {
  enabled: boolean;
  running: boolean;
  nextScanDueAt: string | null;
  lastRunStartedAt: string | null;
  lastError: string | null;
}

interface OperatorActionsProps {
  schedulerEnabled?: boolean;
  schedulerRunning: boolean;
  nextScanDueAt?: string | null;
  lastSchedulerRunStartedAt?: string | null;
  lastSchedulerError?: string | null;
  readyzPollAttempts?: number;
  readyzPollIntervalMs?: number;
}

const READYZ_POLL_ATTEMPTS = 5;
const READYZ_POLL_INTERVAL_MS = 1000;
const WORKER_NOT_RUNNING_MESSAGE =
  'Scheduler enabled, but worker is not running. Start it with: python -m app.worker from services/scanner/.';

function schedulerSnapshotFromProps({
  schedulerEnabled,
  schedulerRunning,
  nextScanDueAt,
  lastSchedulerRunStartedAt,
  lastSchedulerError,
}: OperatorActionsProps): SchedulerSnapshot {
  return {
    enabled: schedulerEnabled ?? schedulerRunning,
    running: schedulerRunning,
    nextScanDueAt: nextScanDueAt ?? null,
    lastRunStartedAt: lastSchedulerRunStartedAt ?? null,
    lastError: lastSchedulerError ?? null,
  };
}

function schedulerSnapshotFromReadyz(health: Partial<HealthResponse>): SchedulerSnapshot {
  const running = health.scheduler_running === true;

  return {
    enabled: health.scheduler_enabled === true || running,
    running,
    nextScanDueAt: health.next_scan_due_at ?? null,
    lastRunStartedAt: health.last_scheduler_run_started_at ?? null,
    lastError: health.last_scheduler_error ?? null,
  };
}

function getReadyzUrl() {
  const scannerBase = process.env.NEXT_PUBLIC_SCANNER_API_BASE || 'http://localhost:8005';
  return `${scannerBase.replace(/\/$/, '')}/readyz`;
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return 'none';
  }

  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return value;
  }

  return new Date(timestamp).toLocaleString();
}

function truncateSchedulerError(value: string | null): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return 'none';
  }

  return trimmed.length > 120 ? `${trimmed.slice(0, 117)}...` : trimmed;
}

export function OperatorActions(props: OperatorActionsProps) {
  const {
    schedulerEnabled,
    schedulerRunning,
    nextScanDueAt,
    lastSchedulerRunStartedAt,
    lastSchedulerError,
    readyzPollAttempts = READYZ_POLL_ATTEMPTS,
    readyzPollIntervalMs = READYZ_POLL_INTERVAL_MS,
  } = props;
  const router = useRouter();
  const [scanBusy, setScanBusy] = useState(false);
  const [schedulerBusy, setSchedulerBusy] = useState(false);
  const [schedulerSnapshot, setSchedulerSnapshot] = useState<SchedulerSnapshot>(() =>
    schedulerSnapshotFromProps(props),
  );
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setSchedulerSnapshot(
      schedulerSnapshotFromProps({
        schedulerEnabled,
        schedulerRunning,
        nextScanDueAt,
        lastSchedulerRunStartedAt,
        lastSchedulerError,
      }),
    );
  }, [
    lastSchedulerError,
    lastSchedulerRunStartedAt,
    nextScanDueAt,
    schedulerEnabled,
    schedulerRunning,
  ]);

  const showFeedback = useCallback((message: string, tone: FeedbackState['tone']) => {
    if (feedbackTimerRef.current) {
      clearTimeout(feedbackTimerRef.current);
    }

    setFeedback({ message, tone });
    feedbackTimerRef.current = setTimeout(() => {
      setFeedback(null);
      feedbackTimerRef.current = null;
    }, 3000);
  }, []);

  useEffect(
    () => () => {
      if (feedbackTimerRef.current) {
        clearTimeout(feedbackTimerRef.current);
      }
    },
    [],
  );

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
        showFeedback(await readErrorMessage(res), 'negative');
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

  const fetchReadyzSnapshot = useCallback(async (): Promise<SchedulerSnapshot | null> => {
    try {
      const res = await fetch(getReadyzUrl(), { cache: 'no-store' });
      if (!res.ok) {
        return null;
      }

      return schedulerSnapshotFromReadyz((await res.json()) as Partial<HealthResponse>);
    } catch {
      return null;
    }
  }, []);

  const pollSchedulerRunning = useCallback(async () => {
    let latestSnapshot: SchedulerSnapshot | null = null;

    for (let attempt = 1; attempt <= readyzPollAttempts; attempt += 1) {
      const snapshot = await fetchReadyzSnapshot();
      if (snapshot) {
        latestSnapshot = snapshot;
        setSchedulerSnapshot(snapshot);
        if (snapshot.running) {
          return { running: true, snapshot };
        }
      }

      if (attempt < readyzPollAttempts) {
        await delay(readyzPollIntervalMs);
      }
    }

    return { running: false, snapshot: latestSnapshot };
  }, [fetchReadyzSnapshot, readyzPollAttempts, readyzPollIntervalMs]);

  const handleScheduler = useCallback(async () => {
    const action = schedulerSnapshot.enabled ? 'stop' : 'start';
    setSchedulerBusy(true);
    try {
      const res = await fetch('/api/scan/scheduler', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      if (res.status === 503) {
        setUnavailable(true);
        showFeedback('Admin controls unavailable', 'muted');
        return;
      }
      if (!res.ok) {
        showFeedback(await readErrorMessage(res), 'negative');
        return;
      }

      if (action === 'start') {
        const result = await pollSchedulerRunning();
        if (!result.snapshot) {
          setSchedulerSnapshot((current) => ({ ...current, enabled: true, running: false }));
        }
        showFeedback(
          result.running ? 'Scheduler enabled and worker is running' : WORKER_NOT_RUNNING_MESSAGE,
          result.running ? 'positive' : 'negative',
        );
      } else {
        setSchedulerSnapshot((current) => ({
          ...current,
          enabled: false,
          running: false,
          nextScanDueAt: null,
        }));
        showFeedback('Scheduler disabled', 'positive');
      }

      router.refresh();
    } catch {
      showFeedback('Network error updating scheduler', 'negative');
    } finally {
      setSchedulerBusy(false);
    }
  }, [pollSchedulerRunning, router, schedulerSnapshot.enabled, showFeedback]);

  if (unavailable) {
    return (
      <p className="muted small" style={{ marginBottom: 12 }}>
        Admin controls unavailable.
      </p>
    );
  }

  const schedulerStatusClass = schedulerSnapshot.running
    ? 'positive'
    : schedulerSnapshot.enabled
      ? 'neutral'
      : 'muted';
  const schedulerStatusLabel = schedulerSnapshot.enabled
    ? schedulerSnapshot.running
      ? 'Scheduler enabled, worker running'
      : 'Scheduler enabled, worker not running'
    : 'Scheduler disabled';
  const schedulerError = truncateSchedulerError(schedulerSnapshot.lastError);

  return (
    <div
      style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}
    >
      <span className={`small ${schedulerStatusClass}`}>{schedulerStatusLabel}</span>
      <button
        className="button"
        disabled={scanBusy}
        onClick={handleScan}
        style={{ width: 'auto', padding: '8px 16px' }}
      >
        {scanBusy ? 'Running...' : 'Run scan now'}
      </button>
      <div style={{ display: 'grid', gap: 4 }}>
        <button
          className="button"
          disabled={schedulerBusy}
          onClick={handleScheduler}
          style={{ width: 'auto', padding: '8px 16px' }}
        >
          {schedulerBusy
            ? schedulerSnapshot.enabled
              ? 'Stopping...'
              : 'Starting...'
            : schedulerSnapshot.enabled
              ? 'Stop scheduler'
              : 'Start scheduler'}
        </button>
        <div className="small muted" style={{ display: 'grid', gap: 2, lineHeight: 1.35 }}>
          <span className={schedulerStatusClass}>
            Scheduler enabled: {schedulerSnapshot.enabled ? 'yes' : 'no'} | Worker running:{' '}
            {schedulerSnapshot.running ? 'yes' : 'no'}
          </span>
          <span>Next scan due: {formatTimestamp(schedulerSnapshot.nextScanDueAt)}</span>
          <span>Last run started: {formatTimestamp(schedulerSnapshot.lastRunStartedAt)}</span>
          <span title={schedulerSnapshot.lastError ?? undefined}>
            Last scheduler error: {schedulerError}
          </span>
        </div>
      </div>
      {feedback ? <span className={`small ${feedback.tone}`}>{feedback.message}</span> : null}
    </div>
  );
}
