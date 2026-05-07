import type {
  AssetType,
  CohortValidationSummary,
  ExecutionAlignmentResponse,
  ExecutionAuditSummary,
  JournalEntry,
  PaperLedgerSummary,
  PaperPositionSummary,
  ValidationSummary,
} from '@/lib/types';

export type PersonalReviewReadinessBand = 'high' | 'watch' | 'low' | 'none';
export type PersonalReviewProviderState = 'fresh' | 'stale' | 'unknown';

export const READINESS_BAND_CUTOFFS = {
  high: 70,
  watch: 50,
  low: 25,
} as const;

export const LOW_SAMPLE_SIZE = 5;

const READINESS_BAND_ORDER: PersonalReviewReadinessBand[] = ['high', 'watch', 'low', 'none'];
const ASSET_TYPE_ORDER: AssetType[] = ['stock', 'crypto'];
const PROVIDER_STATE_ORDER: PersonalReviewProviderState[] = ['fresh', 'stale', 'unknown'];

const READINESS_BAND_LABELS: Record<PersonalReviewReadinessBand, string> = {
  high: 'High readiness',
  watch: 'Watch readiness',
  low: 'Low readiness',
  none: 'No readiness',
};

const PROVIDER_STATE_LABELS: Record<PersonalReviewProviderState, string> = {
  fresh: 'Fresh provider data',
  stale: 'Stale provider data',
  unknown: 'Unknown provider data',
};

type OutcomeRecord = {
  id: string;
  ticker: string;
  assetType: AssetType;
  readinessBand: PersonalReviewReadinessBand;
  providerState: PersonalReviewProviderState;
  pnlUsd: number;
  pnlPct: number | null;
};

export type PersonalReviewAggregate = {
  key: string;
  label: string;
  sampleSize: number;
  winCount: number;
  lossCount: number;
  flatCount: number;
  winRatePct: number | null;
  avgPnlUsd: number | null;
  avgPnlPct: number | null;
  totalPnlUsd: number;
  baselineSampleSize: number;
  baselineWinRatePct: number | null;
  baselineAvgPnlUsd: number | null;
  baselineAvgPnlPct: number | null;
  lowSample: boolean;
};

export type PersonalReviewMissedWinsEstimator = {
  sampleSize: number;
  estimatedMissedWins: number;
  winRatePct: number | null;
  avgPositivePnlPct: number | null;
  totalPositivePnlPct: number;
  blockedButWatchedPositiveCount: number;
  lowSample: boolean;
};

export type PersonalReviewCohortContext = {
  label: string;
  sampleSize: number;
  evaluatedCount: number;
  winRatePct: number | null;
  avgReturnPct: number | null;
  expectancyPct: number | null;
};

export type PersonalReviewResult = {
  baseline: PersonalReviewAggregate;
  aggregateByReadinessBand: PersonalReviewAggregate[];
  aggregateByAssetType: PersonalReviewAggregate[];
  aggregateByProviderState: PersonalReviewAggregate[];
  blockedButWatchedCount: number;
  missedWinsEstimator: PersonalReviewMissedWinsEstimator;
  paperSummary: {
    totalCount: number;
    openPositions: number;
    closedPositions: number;
    winRatePct: number | null;
    totalRealizedPnlUsd: number;
    grossPnlUsd: number;
    maxDrawdownUsd: number;
  };
  validationContext: PersonalReviewCohortContext | null;
  alignmentContext: PersonalReviewCohortContext[];
  warnings: string[];
  assumptions: string[];
};

export type BuildPersonalReviewInput = {
  validation: ValidationSummary | null;
  executionAlignment: ExecutionAlignmentResponse | null;
  paperLedger: PaperPositionSummary[];
  paperLedgerSummary: PaperLedgerSummary | null;
  journalEntries: JournalEntry[];
  audits: ExecutionAuditSummary[];
};

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function finiteCount(value: number | null | undefined, fallback = 0): number {
  const safeValue = finiteNumber(value);
  if (safeValue == null) return fallback;
  return Math.max(0, Math.round(safeValue));
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function percent(numerator: number, denominator: number): number | null {
  if (denominator <= 0) return null;
  return round((numerator / denominator) * 100);
}

function average(values: number[]): number | null {
  if (!values.length) return null;
  return round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function sum(values: number[]): number {
  return round(values.reduce((total, value) => total + value, 0));
}

export function readinessBandForScore(
  score: number | null | undefined,
): PersonalReviewReadinessBand {
  const safeScore = finiteNumber(score);
  if (safeScore == null) return 'none';
  if (safeScore >= READINESS_BAND_CUTOFFS.high) return 'high';
  if (safeScore >= READINESS_BAND_CUTOFFS.watch) return 'watch';
  if (safeScore >= READINESS_BAND_CUTOFFS.low) return 'low';
  return 'none';
}

function providerStateForAudit(
  audit: ExecutionAuditSummary | null | undefined,
): PersonalReviewProviderState {
  if (audit?.latest_scan_fresh === true) return 'fresh';
  if (audit?.latest_scan_fresh === false) return 'stale';
  return 'unknown';
}

function positionPnlPct(position: PaperPositionSummary): number | null {
  const realizedPnl = finiteNumber(position.realized_pnl);
  const costBasis = finiteNumber(position.cost_basis_usd);
  if (realizedPnl != null && costBasis != null && costBasis > 0) {
    return round((realizedPnl / costBasis) * 100);
  }

  const closePrice = finiteNumber(position.close_price);
  const fillPrice = finiteNumber(position.simulated_fill_price);
  if (closePrice == null || fillPrice == null || fillPrice <= 0) return null;

  const sideMultiplier = position.side === 'buy' ? 1 : -1;
  return round(((closePrice - fillPrice) / fillPrice) * 100 * sideMultiplier);
}

function buildOutcomeRecords(
  positions: PaperPositionSummary[],
  audits: ExecutionAuditSummary[],
): OutcomeRecord[] {
  const auditById = new Map(audits.map((audit) => [audit.id, audit]));

  return positions.flatMap((position) => {
    const pnlUsd = finiteNumber(position.realized_pnl);
    if (position.status !== 'closed' || pnlUsd == null) return [];

    const audit =
      position.execution_audit_id != null ? auditById.get(position.execution_audit_id) : null;

    return [
      {
        id: String(position.id),
        ticker: position.ticker,
        assetType: position.asset_type,
        readinessBand: readinessBandForScore(position.confidence),
        providerState: providerStateForAudit(audit),
        pnlUsd,
        pnlPct: positionPnlPct(position),
      },
    ];
  });
}

function summarizeRecords(
  key: string,
  label: string,
  records: OutcomeRecord[],
  baseline?: PersonalReviewAggregate,
): PersonalReviewAggregate {
  const sampleSize = records.length;
  const winCount = records.filter((record) => record.pnlUsd > 0).length;
  const lossCount = records.filter((record) => record.pnlUsd < 0).length;
  const flatCount = sampleSize - winCount - lossCount;
  const pnlUsdValues = records.map((record) => record.pnlUsd);
  const pnlPctValues = records.flatMap((record) => (record.pnlPct == null ? [] : [record.pnlPct]));

  return {
    key,
    label,
    sampleSize,
    winCount,
    lossCount,
    flatCount,
    winRatePct: percent(winCount, sampleSize),
    avgPnlUsd: average(pnlUsdValues),
    avgPnlPct: average(pnlPctValues),
    totalPnlUsd: sum(pnlUsdValues),
    baselineSampleSize: baseline?.sampleSize ?? sampleSize,
    baselineWinRatePct: baseline?.winRatePct ?? percent(winCount, sampleSize),
    baselineAvgPnlUsd: baseline?.avgPnlUsd ?? average(pnlUsdValues),
    baselineAvgPnlPct: baseline?.avgPnlPct ?? average(pnlPctValues),
    lowSample: sampleSize > 0 && sampleSize < LOW_SAMPLE_SIZE,
  };
}

function aggregateByReadinessBand(
  records: OutcomeRecord[],
  baseline: PersonalReviewAggregate,
): PersonalReviewAggregate[] {
  return READINESS_BAND_ORDER.map((band) =>
    summarizeRecords(
      band,
      READINESS_BAND_LABELS[band],
      records.filter((record) => record.readinessBand === band),
      baseline,
    ),
  );
}

function aggregateByAssetType(
  records: OutcomeRecord[],
  baseline: PersonalReviewAggregate,
): PersonalReviewAggregate[] {
  return ASSET_TYPE_ORDER.map((assetType) =>
    summarizeRecords(
      assetType,
      assetType === 'stock' ? 'Stocks' : 'Crypto',
      records.filter((record) => record.assetType === assetType),
      baseline,
    ),
  );
}

function aggregateByProviderState(
  records: OutcomeRecord[],
  baseline: PersonalReviewAggregate,
): PersonalReviewAggregate[] {
  return PROVIDER_STATE_ORDER.map((state) =>
    summarizeRecords(
      state,
      PROVIDER_STATE_LABELS[state],
      records.filter((record) => record.providerState === state),
      baseline,
    ),
  );
}

function signalKey(ticker: string | null | undefined, runId: string | null | undefined) {
  const cleanTicker = ticker?.trim().toUpperCase();
  const cleanRunId = runId?.trim();
  if (!cleanTicker || !cleanRunId) return null;
  return `${cleanRunId}::${cleanTicker}`;
}

function auditIsGateBlocked(audit: ExecutionAuditSummary): boolean {
  return audit.trade_gate_allowed === false || audit.stored_gate_passed === false;
}

function journalEntryIsWatched(entry: JournalEntry): boolean {
  return entry.decision === 'watching' || entry.action_state === 'watching';
}

function journalEntryIsSkippedOrWatched(entry: JournalEntry): boolean {
  return (
    entry.decision === 'skipped' ||
    entry.decision === 'watching' ||
    entry.action_state === 'skipped' ||
    entry.action_state === 'watching'
  );
}

function blockedWatchedEntryIds(
  journalEntries: JournalEntry[],
  audits: ExecutionAuditSummary[],
): Set<number> {
  const blockedSignalKeys = new Set(
    audits.flatMap((audit) => {
      if (!auditIsGateBlocked(audit)) return [];
      const key = signalKey(audit.ticker, audit.signal_run_id);
      return key ? [key] : [];
    }),
  );

  return new Set(
    journalEntries.flatMap((entry) => {
      if (!journalEntryIsWatched(entry)) return [];
      const key = signalKey(entry.ticker, entry.run_id);
      return key && blockedSignalKeys.has(key) ? [entry.id] : [];
    }),
  );
}

function estimateMissedWins(
  journalEntries: JournalEntry[],
  blockedWatchedIds: Set<number>,
): PersonalReviewMissedWinsEstimator {
  const evaluated = journalEntries.filter(
    (entry) => journalEntryIsSkippedOrWatched(entry) && finiteNumber(entry.pnl_pct) != null,
  );
  const positive = evaluated.filter((entry) => finiteNumber(entry.pnl_pct)! > 0);
  const positivePnlValues = positive.map((entry) => finiteNumber(entry.pnl_pct)!);

  return {
    sampleSize: evaluated.length,
    estimatedMissedWins: positive.length,
    winRatePct: percent(positive.length, evaluated.length),
    avgPositivePnlPct: average(positivePnlValues),
    totalPositivePnlPct: sum(positivePnlValues),
    blockedButWatchedPositiveCount: positive.filter((entry) => blockedWatchedIds.has(entry.id))
      .length,
    lowSample: evaluated.length > 0 && evaluated.length < LOW_SAMPLE_SIZE,
  };
}

function paperSummary(
  positions: PaperPositionSummary[],
  summary: PaperLedgerSummary | null,
): PersonalReviewResult['paperSummary'] {
  const openFallback = positions.filter((position) => position.status === 'open').length;
  const closedFallback = positions.filter((position) => position.status === 'closed').length;

  return {
    totalCount: finiteCount(summary?.total_count, positions.length),
    openPositions: finiteCount(summary?.open_positions, openFallback),
    closedPositions: finiteCount(summary?.closed_positions, closedFallback),
    winRatePct: finiteNumber(summary?.win_rate_pct),
    totalRealizedPnlUsd: finiteNumber(summary?.total_realized_pnl) ?? 0,
    grossPnlUsd: finiteNumber(summary?.gross_pnl_usd) ?? 0,
    maxDrawdownUsd: finiteNumber(summary?.max_drawdown_usd) ?? 0,
  };
}

function validationContext(validation: ValidationSummary | null): PersonalReviewCohortContext | null {
  if (!validation) return null;
  return {
    label: 'All validated signals',
    sampleSize: finiteCount(validation.total_signals),
    evaluatedCount: finiteCount(validation.evaluated_count),
    winRatePct: finiteNumber(validation.overall.win_rate),
    avgReturnPct: finiteNumber(validation.overall.avg_return),
    expectancyPct: finiteNumber(validation.overall.expectancy_after_friction),
  };
}

function cohortContext(
  label: string,
  cohort: CohortValidationSummary | null | undefined,
): PersonalReviewCohortContext | null {
  if (!cohort) return null;
  return {
    label,
    sampleSize: finiteCount(cohort.total_signals),
    evaluatedCount: finiteCount(cohort.evaluated_count),
    winRatePct: finiteNumber(cohort.win_rate),
    avgReturnPct: finiteNumber(cohort.avg_return),
    expectancyPct: finiteNumber(cohort.expectancy_after_friction ?? cohort.expectancy),
  };
}

function alignmentContexts(
  alignment: ExecutionAlignmentResponse | null,
): PersonalReviewCohortContext[] {
  if (!alignment) return [];

  return [
    cohortContext('All scanner signals', alignment.all_signals),
    cohortContext('Taken paper trades', alignment.taken_trades),
    cohortContext('Skipped or watched', alignment.skipped_or_watched),
    cohortContext('Blocked previews', alignment.blocked_previews),
  ].filter((context): context is PersonalReviewCohortContext => context != null);
}

function buildWarnings(records: OutcomeRecord[]): string[] {
  const warnings: string[] = ['Low sample sizes can be misleading.'];

  if (!records.length) {
    warnings.push('No closed paper outcomes are available yet.');
  } else if (records.length < LOW_SAMPLE_SIZE) {
    warnings.push(`Only ${records.length} closed paper outcome${records.length === 1 ? '' : 's'}.`);
  }

  if (records.every((record) => record.providerState === 'unknown')) {
    warnings.push('Provider status is not stored on paper outcomes; unmatched rows are unknown.');
  }

  return warnings;
}

export function buildPersonalReview(input: BuildPersonalReviewInput): PersonalReviewResult {
  const records = buildOutcomeRecords(input.paperLedger, input.audits);
  const baseline = summarizeRecords('baseline', 'All closed paper outcomes', records);
  const blockedWatchedIds = blockedWatchedEntryIds(input.journalEntries, input.audits);

  return {
    baseline,
    aggregateByReadinessBand: aggregateByReadinessBand(records, baseline),
    aggregateByAssetType: aggregateByAssetType(records, baseline),
    aggregateByProviderState: aggregateByProviderState(records, baseline),
    blockedButWatchedCount: blockedWatchedIds.size,
    missedWinsEstimator: estimateMissedWins(input.journalEntries, blockedWatchedIds),
    paperSummary: paperSummary(input.paperLedger, input.paperLedgerSummary),
    validationContext: validationContext(input.validation),
    alignmentContext: alignmentContexts(input.executionAlignment),
    warnings: buildWarnings(records),
    assumptions: [
      'Readiness usefulness is estimated from closed paper-ledger outcomes grouped by the confidence snapshot stored with each paper position.',
      'Journal missed-win estimates use watched or skipped entries that have an entered P/L percent.',
      'Blocked-but-watched counts require an exact journal run ID and ticker match to a blocked execution audit.',
    ],
  };
}
