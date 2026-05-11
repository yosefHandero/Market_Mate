'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  buildFrequentWatchTickers,
  shouldNotify,
  type PersonalAlertMatch,
} from '@/lib/personal-alerts';
import { formatReadiness } from '@/lib/readiness';
import { getScannerApiBase, readErrorMessage } from '@/lib/scanner-api';
import type { JournalEntry, ScanRun } from '@/lib/types';

const STORAGE_KEY = 'market-mate.personal-alerts.enabled';
const POLL_INTERVAL_MS = 30_000;
const READINESS_THRESHOLD = 70;

type PermissionStatus = NotificationPermission | 'unsupported';

function readStoredOptIn(storageKey: string): boolean {
  try {
    return window.localStorage.getItem(storageKey) === 'true';
  } catch {
    return false;
  }
}

function writeStoredOptIn(storageKey: string, enabled: boolean) {
  try {
    window.localStorage.setItem(storageKey, enabled ? 'true' : 'false');
  } catch {
    // Local alerts still work for the current session if storage is unavailable.
  }
}

function currentPermission(): PermissionStatus {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return 'unsupported';
  }

  return window.Notification.permission;
}

async function requestPermissionAfterClick(): Promise<PermissionStatus> {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return 'unsupported';
  }

  if (window.Notification.permission !== 'default') {
    return window.Notification.permission;
  }

  return window.Notification.requestPermission();
}

async function defaultFetchLatestScan(): Promise<ScanRun | null> {
  const response = await fetch(`${getScannerApiBase()}/scan/latest`, { cache: 'no-store' });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ScanRun | null;
}

function notify(match: PersonalAlertMatch) {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return;
  }

  new window.Notification(`Market Mate: ${match.ticker} Readiness ${match.readinessScore}%`, {
    body: `${match.row.decision_signal} signal on a frequent watcher. Latest readiness is ${formatReadiness(
      match.readinessScore,
    )}.`,
    tag: match.id,
  });
}

export function PersonalAlerts({
  initialLatestScan,
  journalEntries = [],
  watchTickers,
  journalError,
  threshold = READINESS_THRESHOLD,
  pollMs = POLL_INTERVAL_MS,
  storageKey = STORAGE_KEY,
  fetchLatestScan = defaultFetchLatestScan,
}: {
  initialLatestScan: ScanRun | null;
  journalEntries?: JournalEntry[];
  watchTickers?: string[];
  journalError?: string | null;
  threshold?: number;
  pollMs?: number;
  storageKey?: string;
  fetchLatestScan?: () => Promise<ScanRun | null>;
}) {
  const [enabled, setEnabled] = useState(false);
  const [permission, setPermission] = useState<PermissionStatus>('unsupported');
  const [statusMessage, setStatusMessage] = useState('Alerts are off.');
  const [lastAlertMessage, setLastAlertMessage] = useState<string | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const frequentWatchTickers = useMemo(
    () => watchTickers ?? buildFrequentWatchTickers(journalEntries),
    [journalEntries, watchTickers],
  );

  const clearPoll = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const processScan = useCallback(
    (scan: ScanRun | null) => {
      const matches = shouldNotify(scan, seenIdsRef.current, threshold, frequentWatchTickers);
      if (!matches.length) {
        return;
      }

      for (const match of matches) {
        seenIdsRef.current.add(match.id);
        notify(match);
      }

      setLastAlertMessage(
        `Last local alert: ${matches.map((match) => match.ticker).join(', ')}`,
      );
    },
    [frequentWatchTickers, threshold],
  );

  const pollLatestScan = useCallback(async () => {
    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
      return;
    }

    try {
      const scan = await fetchLatestScan();
      processScan(scan);
      setStatusMessage('Alerts are on. Watching latest visible scans.');
    } catch (error) {
      setStatusMessage(
        error instanceof Error ? `Alert polling failed: ${error.message}` : 'Alert polling failed.',
      );
    }
  }, [fetchLatestScan, processScan]);

  useEffect(() => {
    const nextPermission = currentPermission();
    setPermission(nextPermission);

    const storedOptIn = readStoredOptIn(storageKey);
    const canResume = storedOptIn && nextPermission === 'granted';
    setEnabled(canResume);
    setStatusMessage(canResume ? 'Alerts are on. Watching latest visible scans.' : 'Alerts are off.');
  }, [storageKey]);

  useEffect(() => {
    if (!enabled || permission !== 'granted' || !frequentWatchTickers.length) {
      clearPoll();
      return;
    }

    const startPoll = () => {
      clearPoll();
      if (document.visibilityState === 'visible') {
        intervalRef.current = setInterval(() => {
          void pollLatestScan();
        }, pollMs);
      }
    };

    startPoll();
    document.addEventListener('visibilitychange', startPoll);

    return () => {
      document.removeEventListener('visibilitychange', startPoll);
      clearPoll();
    };
  }, [clearPoll, enabled, frequentWatchTickers.length, permission, pollLatestScan, pollMs]);

  const handleToggle = async () => {
    if (enabled) {
      setEnabled(false);
      writeStoredOptIn(storageKey, false);
      setStatusMessage('Alerts are off.');
      clearPoll();
      return;
    }

    const nextPermission = await requestPermissionAfterClick();
    setPermission(nextPermission);

    if (nextPermission !== 'granted') {
      setEnabled(false);
      writeStoredOptIn(storageKey, false);
      setStatusMessage(
        nextPermission === 'denied'
          ? 'Browser notification permission is denied.'
          : 'Browser notifications are unavailable.',
      );
      return;
    }

    seenIdsRef.current = new Set(seenIdsRef.current);
    writeStoredOptIn(storageKey, true);
    setEnabled(true);
    setStatusMessage('Alerts are on. Watching latest visible scans.');
    processScan(initialLatestScan);
  };

  const denied = permission === 'denied';
  const unsupported = permission === 'unsupported';
  const watcherCopy =
    frequentWatchTickers.length > 0
      ? `${frequentWatchTickers.length} frequent watcher ticker${
          frequentWatchTickers.length === 1 ? '' : 's'
        } loaded.`
      : 'No frequent watcher tickers are loaded yet.';

  return (
    <section className="detail-panel" aria-label="Personal browser alerts">
      <div className="header-row" style={{ marginBottom: 0 }}>
        <div>
          <strong>Local Browser Alerts</strong>
          <div className="muted small">
            Optional local notifications for frequent watchers at Readiness {threshold}+.
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          className={`button ${enabled ? 'amber' : ''}`}
          onClick={handleToggle}
        >
          Browser alerts: {enabled ? 'On' : 'Off'}
        </button>
      </div>

      <div className="small muted">{statusMessage}</div>
      <div className="small muted">{watcherCopy}</div>
      {lastAlertMessage ? <div className="small positive">{lastAlertMessage}</div> : null}
      {journalError ? <div className="small negative">{journalError}</div> : null}
      {denied ? (
        <div className="small negative">
          Browser notification permission is denied. Enable notifications in this browser&apos;s site
          settings to use local alerts.
        </div>
      ) : null}
      {unsupported ? (
        <div className="small muted">This browser does not support local notifications.</div>
      ) : null}
    </section>
  );
}
