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
  onRefresh?: () => void;
  feedbackClearMs?: number;
}

const READYZ_POLL_ATTEMPTS = 5;
const READYZ_POLL_INTERVAL_MS = 1000;
export const APP_START_COMMAND = 'powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\windows\\Start-MarketMate.ps1';
export const WORKER_NOT_RUNNING_MESSAGE =
  'Scheduler is on, but the local worker is not running. Auto-scans will not run until the worker starts.';
const WORKER_IMPACT_MESSAGE =
  'Without the worker, scans go stale, readiness scores drop, and ranks may not update until you run a manual scan.';

function schedulerSnapshotFromProps({
  schedulerEnabled,
  schedulerRunning,
  nextScanDueAt,
  lastSchedulerRunStartedAt,
  lastSchedulerError,
}: OperatorActionsProps): SchedulerSnapshot {
  return {
    enabled: schedulerEnabled === true,
    running: schedulerRunning,
    nextScanDueAt: nextScanDueAt ?? null,
    lastRunStartedAt: lastSchedulerRunStartedAt ?? null,
    lastError: lastSchedulerError ?? null,
  };
}

function workerRunningFromHealth(health: Partial<HealthResponse>): boolean {
  if (health.worker_alive != null) {
    return health.worker_alive === true;
  }
  return health.scheduler_running === true;
}

function schedulerSnapshotFromReadyz(health: Partial<HealthResponse>): SchedulerSnapshot {
  const running = workerRunningFromHealth(health);

  return {
    enabled: health.scheduler_enabled === true,
    running,
    nextScanDueAt: health.next_scan_due_at ?? null,
    lastRunStartedAt: health.last_scheduler_run_started_at ?? null,
    lastError: health.last_scheduler_error ?? null,
  };
}

function getReadyzUrl() {
  return '/api/scan/readyz';
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
  const router = useRouter();
  return (
    <OperatorActionsPanel
      {...props}
      onRefresh={props.onRefresh ?? (() => router.refresh())}
    />
  );
}

export function OperatorActionsPanel({
  schedulerEnabled,
  schedulerRunning,
  nextScanDueAt,
  lastSchedulerRunStartedAt,
  lastSchedulerError,
  readyzPollAttempts = READYZ_POLL_ATTEMPTS,
  readyzPollIntervalMs = READYZ_POLL_INTERVAL_MS,
  onRefresh,
  feedbackClearMs = 3000,
}: OperatorActionsProps & { onRefresh: () => void }) {
  const props = {
    schedulerEnabled,
    schedulerRunning,
    nextScanDueAt,
    lastSchedulerRunStartedAt,
    lastSchedulerError,
    readyzPollAttempts,
    readyzPollIntervalMs,
  };
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
    }, feedbackClearMs);
  }, [feedbackClearMs]);

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
      onRefresh();
    } catch {
      showFeedback('Network error triggering scan', 'negative');
    } finally {
      setScanBusy(false);
    }
  }, [onRefresh, showFeedback]);

  const fetchReadyzSnapshot = useCallback(async (): Promise<SchedulerSnapshot | null> => {
    const readyzUrl = getReadyzUrl();
    try {
      const res = await fetch(readyzUrl, { cache: 'no-store' });
      if (!res.ok) {
        return null;
      }

      const snapshot = schedulerSnapshotFromReadyz((await res.json()) as Partial<HealthResponse>);
      return snapshot;
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
          showFeedback(
            'Scheduler start submitted, but readiness check is unavailable. Refresh to confirm state.',
            'negative',
          );
        } else {
          showFeedback(
            result.running
              ? 'Scheduler and worker are running.'
              : WORKER_NOT_RUNNING_MESSAGE,
            result.running ? 'positive' : 'negative',
          );
        }
      } else {
        setSchedulerSnapshot((current) => ({
          ...current,
          enabled: false,
          running: false,
          nextScanDueAt: null,
        }));
        showFeedback('Scheduler disabled', 'positive');
      }

      onRefresh();
    } catch {
      showFeedback('Network error updating scheduler', 'negative');
    } finally {
      setSchedulerBusy(false);
    }
  }, [onRefresh, pollSchedulerRunning, schedulerSnapshot.enabled, showFeedback]);

  if (unavailable) {
    return (
      <p className="muted small" style={{ marginBottom: 12 }}>
        Admin controls unavailable.
      </p>
    );
  }

  const schedulerError = truncateSchedulerError(schedulerSnapshot.lastError);
  const showWorkerBanner = schedulerSnapshot.enabled && !schedulerSnapshot.running;
  const showWorkerRunningNoScheduler = !schedulerSnapshot.enabled && schedulerSnapshot.running;

  const copyToClipboard = async (text: string, successMessage: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showFeedback(successMessage, 'positive');
    } catch {
      window.prompt('Copy:', text);
    }
  };

  const copyAppStartCommand = () =>
    void copyToClipboard(
      APP_START_COMMAND,
      'App startup command copied. Run it from the repository root.',
    );

  return (
    <section className="scheduler-operator-panel" aria-label="Local operator controls">
      {showWorkerBanner ? (
        <div
          className="scheduler-operator-banner scheduler-operator-banner-warning"
          role="status"
          data-testid="worker-not-running-banner"
        >
          <p className="small" style={{ margin: 0 }}>
            {WORKER_NOT_RUNNING_MESSAGE}
          </p>
        </div>
      ) : null}

      {showWorkerRunningNoScheduler ? (
        <div className="scheduler-operator-banner scheduler-operator-banner-warning" role="status">
          <p className="small" style={{ margin: 0 }}>
            Worker is running, but the scheduler is disabled. Auto-scans will not start until the
            scheduler is enabled.
          </p>
        </div>
      ) : null}

      <div className="scheduler-operator-actions scheduler-operator-actions-primary">
        <button
          className="button button-primary"
          disabled={scanBusy}
          onClick={handleScan}
          style={{ width: 'auto', padding: '8px 16px' }}
        >
          {scanBusy ? 'Running...' : 'Run scan now'}
        </button>
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
      </div>

      {feedback ? <span className={`small ${feedback.tone}`}>{feedback.message}</span> : null}

      <details className="ui-disclosure scheduler-operator-details">
        <summary className="ui-disclosure-summary muted small">Operator details</summary>
        <p className="muted small" style={{ margin: '8px 0' }}>
          Local operator controls only. The app enables the scheduler; the worker runs scans
          separately.
        </p>
        <div className="scheduler-operator-pills">
          <span
            className={`badge ${schedulerSnapshot.enabled ? 'green' : ''}`}
            title="Scheduler enabled in the scanner API"
          >
            Scheduler: {schedulerSnapshot.enabled ? 'Enabled' : 'Disabled'}
          </span>
          <span
            className={`badge ${schedulerSnapshot.running ? 'green' : 'amber'}`}
            title="Worker process heartbeat"
          >
            Worker: {schedulerSnapshot.running ? 'Running' : 'Not running'}
          </span>
          <span className="badge" title="Next scheduled scan">
            Next scan: {formatTimestamp(schedulerSnapshot.nextScanDueAt)}
          </span>
          <span className="badge" title="Last scheduler run started">
            Last run: {formatTimestamp(schedulerSnapshot.lastRunStartedAt)}
          </span>
        </div>

        {showWorkerBanner ? (
          <>
            <p className="muted small" style={{ margin: '8px 0 0' }}>
              {WORKER_IMPACT_MESSAGE}
            </p>
            <p className="muted small" style={{ margin: '6px 0 0' }}>
              Start the app services from the repository root with <code>{APP_START_COMMAND}</code>.
            </p>
            <div className="scheduler-operator-actions" style={{ marginTop: 8 }} role="group">
              <button
                type="button"
                className="button button-secondary"
                style={{ width: 'auto', padding: '6px 12px' }}
                onClick={copyAppStartCommand}
              >
                Copy app startup command
              </button>
            </div>
          </>
        ) : null}

        {schedulerSnapshot.enabled && schedulerSnapshot.running ? (
          <p className="small positive" style={{ margin: '8px 0 0' }}>
            Scheduler and worker are running. Next scan due{' '}
            {formatTimestamp(schedulerSnapshot.nextScanDueAt)}.
          </p>
        ) : null}

        {!schedulerSnapshot.enabled && !schedulerSnapshot.running ? (
          <p className="muted small" style={{ margin: '8px 0 0' }}>
            Scheduler is disabled. Use Run scan now or Start scheduler for auto-scans.
          </p>
        ) : null}

        {schedulerError !== 'none' ? (
          <p
            className="muted small"
            style={{ margin: '8px 0 0' }}
            title={schedulerSnapshot.lastError ?? undefined}
          >
            Last scheduler error: {schedulerError}
          </p>
        ) : null}
      </details>
    </section>
  );
}
