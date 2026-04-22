import type {
  ActionItem,
  AutomationStatusResponse,
  DecisionRow,
  HealthResponse,
  JournalEntry,
  ScanRun,
} from '@/lib/types';

export function computePendingActions({
  decisions,
  automation,
  journalEntries,
  health,
  latestScan,
}: {
  decisions: DecisionRow[] | null;
  automation: AutomationStatusResponse | null;
  journalEntries: JournalEntry[] | null;
  health: HealthResponse | null;
  latestScan: ScanRun | null;
}): ActionItem[] {
  const items: ActionItem[] = [];

  if (automation) {
    if (!automation.enabled || automation.phase === 'disabled') {
      items.push({
        id: 'paper_loop_disabled',
        type: 'paper_loop_disabled',
        title: 'Paper loop is disabled',
        subtitle:
          'The automated fake-money loop is off. Enable it in your scanner .env to start dry-run automation.',
        metadata: { phase: automation.phase },
      });
    }

    if (automation.kill_switch_enabled) {
      items.push({
        id: 'kill_switch_active',
        type: 'kill_switch_active',
        title: 'Kill switch is active',
        subtitle:
          'All automation is halted by the kill switch. Disable it in your scanner .env to resume.',
        metadata: {},
      });
    }

    if (automation.breaker.state === 'open') {
      items.push({
        id: 'breaker_open',
        type: 'breaker_open',
        title: 'Circuit breaker is open',
        subtitle: automation.breaker.open_until
          ? `Breaker will reset at ${new Date(automation.breaker.open_until).toLocaleString()}.`
          : 'Breaker is open due to consecutive failures.',
        metadata: {
          consecutive_failures: automation.breaker.consecutive_failures,
          last_error: automation.breaker.last_error,
          open_until: automation.breaker.open_until,
        },
      });
    }
  }

  if (health && !health.scheduler_running) {
    items.push({
      id: 'scheduler_stopped',
      type: 'scheduler_stopped',
      title: 'Scheduler is stopped',
      subtitle: 'The scan scheduler is not running. Start it to enable periodic scans.',
      metadata: {},
    });
  }

  const runId = latestScan?.run_id ?? null;
  const journaledTickers = new Set(
    (journalEntries ?? [])
      .filter((e) => e.run_id === runId)
      .map((e) => e.ticker),
  );

  for (const row of decisions ?? []) {
    if (row.execution_eligibility !== 'review') continue;
    if (journaledTickers.has(row.symbol)) continue;

    items.push({
      id: `review:${runId}:${row.symbol}`,
      type: 'review_signal',
      title: `Review: ${row.symbol}`,
      subtitle: `${row.signal} signal · Score ${row.confidence.toFixed(1)} · ${row.evidence_quality ?? 'unknown'} evidence`,
      metadata: {
        symbol: row.symbol,
        signal: row.signal,
        confidence: row.confidence,
        asset_type: row.asset_type,
        run_id: runId,
        price: (latestScan?.results ?? []).find((r) => r.ticker === row.symbol)?.price ?? null,
        signal_label:
          (latestScan?.results ?? []).find((r) => r.ticker === row.symbol)?.signal_label ?? null,
        score: row.confidence,
        news_source:
          (latestScan?.results ?? []).find((r) => r.ticker === row.symbol)?.news_source ?? null,
      },
    });
  }

  for (const entry of journalEntries ?? []) {
    if (entry.decision !== 'watching') continue;

    items.push({
      id: `watching:${entry.id}`,
      type: 'watching_entry',
      title: `Watching: ${entry.ticker}`,
      subtitle: [
        entry.signal_label ? `Signal ${entry.signal_label}` : null,
        entry.score != null ? `Score ${entry.score.toFixed(1)}` : null,
        entry.entry_price != null ? `Entry $${entry.entry_price.toFixed(2)}` : null,
      ]
        .filter(Boolean)
        .join(' · ') || 'Awaiting your decision.',
      metadata: {
        entry_id: entry.id,
        ticker: entry.ticker,
        entry_price: entry.entry_price,
        exit_price: entry.exit_price,
        signal_label: entry.signal_label,
        score: entry.score,
        notes: entry.notes,
      },
    });
  }

  return items;
}
