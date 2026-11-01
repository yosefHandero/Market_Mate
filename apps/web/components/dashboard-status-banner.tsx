import { MarketStatusBadge } from '@/components/market-status-badge';
import type {
  AutomationStatusResponse,
  HealthResponse,
  ScanResult,
  ScanRun,
  SystemReadinessResponse,
} from '@/lib/types';
import {
  FRESH_BAR_MAX_MINUTES,
  isHealthyFreshnessFlag,
  SCAN_FRESH_MAX_MINUTES,
} from '@/lib/freshness';

type StatusTone = 'ok' | 'warning' | 'bad' | 'muted';
const SEVERE_STALE_MINUTES = 360;

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function ageFromTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  // SQLite-backed API timestamps can be timezone-naive; they represent UTC.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const timestamp = Date.parse(normalized);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, (Date.now() - timestamp) / 60_000);
}

function formatMinutes(value: number | null): string {
  if (value == null) return 'unknown';
  return `${Math.round(value)}m`;
}

function providerRank(status: string): number {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'critical' || normalized === 'error') return 3;
  if (normalized === 'degraded') return 2;
  if (normalized === 'ok' || normalized === 'healthy') return 0;
  return 1;
}

function providerState(latestScan: ScanRun | null): { label: string; tone: StatusTone } {
  const statuses = (latestScan?.results ?? []).map((row) => row.provider_status).filter(Boolean);
  if (!statuses.length) return { label: 'unknown', tone: 'muted' };

  const worst = statuses.reduce((current, next) =>
    providerRank(next) > providerRank(current) ? next : current,
  );
  const normalized = worst.trim().toLowerCase();
  if (normalized === 'critical' || normalized === 'error') {
    return { label: normalized, tone: 'bad' };
  }
  if (normalized === 'degraded') return { label: 'degraded', tone: 'warning' };
  if (normalized === 'ok' || normalized === 'healthy') return { label: 'ok', tone: 'ok' };
  return { label: normalized || 'unknown', tone: 'muted' };
}

function rowProviderCritical(row: Pick<ScanResult, 'provider_status'>): boolean {
  const normalized = String(row.provider_status ?? '').trim().toLowerCase();
  return normalized === 'critical' || normalized === 'error';
}

function rowBarAge(row: Pick<ScanResult, 'bar_age_minutes'>): number | null {
  return finiteNumber(row.bar_age_minutes);
}

function displayedBarAge(row: ScanResult, latestScan: ScanRun): number | null {
  const absoluteAge = ageFromTimestamp(row.bar_as_of);
  if (absoluteAge != null) return absoluteAge;
  const storedAge = finiteNumber(row.bar_age_minutes);
  if (storedAge == null) return null;
  // Legacy rows lack bar_as_of. Their stored age was measured at scan time.
  return storedAge + (ageFromTimestamp(row.created_at ?? latestScan.created_at) ?? 0);
}

function barsState(latestScan: ScanRun | null, assetType?: 'stock' | 'crypto'): { label: string; tone: StatusTone } {
  const rows = (latestScan?.results ?? []).filter((row) => !assetType || row.asset_type === assetType);
  const ages = rows
    .map((row) => displayedBarAge(row, latestScan!))
    .filter((age): age is number => age != null);
  if (!ages.length) return { label: 'unknown', tone: 'muted' };

  const maxAge = Math.max(...ages);
  if (maxAge > 1440) return { label: '>24h stale', tone: 'bad' };
  if (maxAge > 360) return { label: '>6h stale', tone: 'bad' };
  if (maxAge > 120) return { label: '>120m stale', tone: 'warning' };
  if (maxAge > FRESH_BAR_MAX_MINUTES) return { label: 'stale', tone: 'warning' };
  return { label: 'fresh', tone: 'ok' };
}

function qualityFlagSummary(latestScan: ScanRun | null): string[] {
  const counts = new Map<string, number>();
  for (const row of latestScan?.results ?? []) {
    for (const [source, flag] of Object.entries(row.freshness_flags ?? {})) {
      if (isHealthyFreshnessFlag(flag)) continue;
      const label = `${source}: ${flag}`;
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  }
  return [...counts].map(([label, count]) => `${label} (${count} ${count === 1 ? 'row' : 'rows'})`);
}

function rowSeverelyStale(row: ScanResult): boolean {
  const age = rowBarAge(row);
  return age != null && age > SEVERE_STALE_MINUTES;
}

function rowUnusableOrStale(row: ScanResult): boolean {
  const age = rowBarAge(row);
  return age == null || age > FRESH_BAR_MAX_MINUTES;
}

function hasSevereGlobalFreshnessFailure({
  health,
  latestScan,
}: {
  health: HealthResponse | null;
  latestScan: ScanRun | null;
}): boolean {
  if (health?.scan_fresh === false) return true;
  const rows = latestScan?.results ?? [];
  if (!rows.length) return false;
  return rows.every((row) => rowSeverelyStale(row));
}

function hasGlobalCriticalProviderFailure(latestScan: ScanRun | null): boolean {
  const rows = latestScan?.results ?? [];
  if (!rows.length) return false;
  return rows.every((row) => rowProviderCritical(row) && rowUnusableOrStale(row));
}

function badgeClass(tone: StatusTone): string {
  if (tone === 'ok') return 'badge green';
  if (tone === 'warning') return 'badge amber';
  if (tone === 'bad') return 'badge red';
  return 'badge';
}

function StatusPill({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone: StatusTone;
  title?: string;
}) {
  return (
    <span className={badgeClass(tone)} style={{ gap: 6 }} title={title}>
      <span className="muted">{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

export type SystemReadinessSummary = {
  status: 'PASS' | 'WARN' | 'FAIL';
  tone: Extract<StatusTone, 'ok' | 'warning' | 'bad'>;
  reasons: string[];
};

const DATA_QUALITY_WARN_REASON = 'Market data quality degraded - signals may be unreliable';

function summarizeServerReadiness(
  serverReadiness: SystemReadinessResponse | null | undefined,
): SystemReadinessSummary | null {
  if (!serverReadiness) return null;
  return {
    status: serverReadiness.status,
    tone: serverReadiness.status === 'PASS' ? 'ok' : 'bad',
    reasons: serverReadiness.reasons.length
      ? serverReadiness.reasons
      : [serverReadiness.status === 'PASS' ? 'Core safety and data checks pass' : 'System readiness failed'],
  };
}

/** Keep input-quality warnings independent of the age-based bar labels. */
function isDataQualityDegraded(
  provider: { tone: StatusTone },
  bars: { tone: StatusTone },
  hasQualityFlags: boolean,
): boolean {
  return provider.tone === 'bad' || bars.tone === 'bad' || bars.tone === 'warning' || hasQualityFlags;
}

/**
 * Downgrade a PASS to WARN when market-data quality is degraded so the System pill
 * never contradicts a critical Provider / stale Bars pill. FAIL always wins.
 */
function applyDataQualityWarning(
  summary: SystemReadinessSummary,
  provider: { tone: StatusTone },
  bars: { tone: StatusTone },
  hasQualityFlags: boolean,
): SystemReadinessSummary {
  if (summary.status !== 'PASS') return summary;
  if (!isDataQualityDegraded(provider, bars, hasQualityFlags)) return summary;
  return {
    status: 'WARN',
    tone: 'warning',
    reasons: [DATA_QUALITY_WARN_REASON],
  };
}

export function computeSystemReadiness({
  health,
  automation,
  latestScan,
}: {
  health: HealthResponse | null;
  automation: AutomationStatusResponse | null;
  latestScan: ScanRun | null;
}): SystemReadinessSummary {
  const reasons: string[] = [];

  if (health?.ok !== true) {
    reasons.push('Backend unavailable');
  }
  if (health?.schema_ok === false || (health?.missing_schema_items?.length ?? 0) > 0) {
    reasons.push('Schema check failed');
  }
  if (automation?.kill_switch_enabled === true) {
    reasons.push('Kill switch on');
  }
  if (automation?.breaker?.state === 'open') {
    reasons.push('Circuit breaker open');
  }
  if (hasSevereGlobalFreshnessFailure({ health, latestScan })) {
    reasons.push('Severe global freshness failure');
  }
  if (hasGlobalCriticalProviderFailure(latestScan)) {
    reasons.push('Provider critical with unusable/stale data');
  }

  return reasons.length
    ? { status: 'FAIL', tone: 'bad', reasons }
    : { status: 'PASS', tone: 'ok', reasons: ['Core safety and data checks pass'] };
}

export function DashboardStatusBanner({
  health,
  automation,
  latestScan,
  systemReadiness: serverReadiness,
  compactDiagnostics = false,
}: {
  health: HealthResponse | null;
  automation: AutomationStatusResponse | null;
  latestScan: ScanRun | null;
  systemReadiness?: SystemReadinessResponse | null;
  /** Hide pills already shown by Proof risk controls. */
  compactDiagnostics?: boolean;
}) {
  const backendOk = health?.ok === true;
  const scanAge =
    ageFromTimestamp(latestScan?.created_at) ?? finiteNumber(health?.last_scan_age_minutes);
  const staleScan = health?.scan_fresh === false || latestScan?.scan_fresh === false ||
    (scanAge != null && scanAge > (health?.max_stale_minutes ?? SCAN_FRESH_MAX_MINUTES));
  const provider = providerState(latestScan);
  const bars = barsState(latestScan);
  const stockBars = barsState(latestScan, 'stock');
  const cryptoBars = barsState(latestScan, 'crypto');
  const qualityFlags = qualityFlagSummary(latestScan);
  const schedulerEnabled = health?.scheduler_enabled === true;
  const workerRunning = health?.worker_alive ?? (health?.scheduler_running === true);
  const killSwitchOn = automation?.kill_switch_enabled === true;
  const breakerState = automation?.breaker?.state ?? 'unknown';
  const breakerOpen = breakerState === 'open';
  const baseReadiness =
    summarizeServerReadiness(serverReadiness) ??
    computeSystemReadiness({ health, automation, latestScan });
  const systemReadiness = applyDataQualityWarning(baseReadiness, provider, bars, qualityFlags.length > 0);
  const safetyActive = killSwitchOn || breakerOpen;
  const dataQualityDegraded = isDataQualityDegraded(provider, bars, qualityFlags.length > 0);

  return (
    <section className="system-health-banner" aria-label="Dashboard status">
      <div className="system-health-primary" data-testid="system-health-primary">
        {compactDiagnostics ? null : (
          <StatusPill
            label="Paper"
            value={automation?.dry_run_only === false ? 'check' : 'dry-run only'}
            tone={automation?.dry_run_only === false ? 'bad' : 'ok'}
            title="Paper mode and dry-run only; no live trading"
          />
        )}
        <StatusPill
          label="System"
          value={systemReadiness.status}
          tone={systemReadiness.tone}
          title={systemReadiness.reasons.join('; ')}
        />
        {compactDiagnostics ? null : (
          <StatusPill
            label="Provider"
            value={staleScan ? `${provider.label} (last scan)` : provider.label}
            tone={staleScan && provider.tone === 'ok' ? 'muted' : provider.tone}
            title="Provider status observed during the last scan; this is not a current connectivity check."
          />
        )}
        <StatusPill label="Stock bars" value={stockBars.label} tone={stockBars.tone} />
        <StatusPill label="Crypto bars" value={cryptoBars.label} tone={cryptoBars.tone} />
        <StatusPill
          label="Real-money trust"
          value={health?.trust_evidence_ready === true ? 'evidence ready' : 'blocked'}
          tone={health?.trust_evidence_ready === true ? 'ok' : 'muted'}
          title={
            'Real-money trust stays blocked until live paper-forward and out-of-sample evidence clears thresholds. Paper dry-run is unaffected.'
          }
        />
      </div>

      {latestScan ? (
        <p className="muted small" data-testid="scan-execution-time">
          Scan execution recorded: {latestScan.created_at} ({formatMinutes(scanAge)} ago).
        </p>
      ) : null}
      {(['stock', 'crypto'] as const).map((assetType) => {
        const rows = (latestScan?.results ?? []).filter((row) => row.asset_type === assetType);
        if (!latestScan || !rows.length) return null;
        const datedRows = rows.filter((row) => ageFromTimestamp(row.bar_as_of) != null);
        const oldest = datedRows.reduce<ScanResult | null>((current, row) =>
          !current || ageFromTimestamp(row.bar_as_of)! > ageFromTimestamp(current.bar_as_of)! ? row : current, null);
        const ages = rows.map((row) => displayedBarAge(row, latestScan)).filter((age): age is number => age != null);
        return (
          <p className="muted small" key={assetType} data-testid={`bar-freshness-${assetType}`}>
            {assetType === 'stock' ? 'Stock' : 'Crypto'} bars: oldest recorded timestamp {oldest?.bar_as_of ?? 'unavailable'};
            {' '}oldest age {formatMinutes(ages.length ? Math.max(...ages) : null)}.
            {' '}Bars become stale above {FRESH_BAR_MAX_MINUTES}m.
          </p>
        );
      })}

      {latestScan ? (
        <p className="muted small" data-testid="scan-coverage">
          Last scan: {latestScan.results.length} analyzed results ({latestScan.results.filter((row) => row.asset_type === 'stock').length} stock,{' '}
          {latestScan.results.filter((row) => row.asset_type === 'crypto').length} crypto) from{' '}
          {latestScan.watchlist_size} configured symbols, including benchmarks.
        </p>
      ) : null}

      {latestScan?.coverage?.length ? (
        <div aria-label="Scan coverage details">
          {latestScan.coverage.map((coverage) => (
            <div key={coverage.asset_type}>
              <p className={`small ${coverage.status === 'complete' ? 'muted' : 'warning'}`}>
                {coverage.asset_type === 'stock' ? 'Stock' : 'Crypto'} coverage: {coverage.returned_symbols.length}/{coverage.expected_symbols.length}{' '}
                symbols analyzed — {coverage.status.replaceAll('_', ' ')}.
                {coverage.status === 'partial' || coverage.status === 'unavailable'
                  ? ' Missing symbols were not evaluated; this is not a full scan.' : ''}
              </p>
              {coverage.missing_symbols.length ? (
                <details className="ui-disclosure">
                  <summary className="ui-disclosure-summary small">
                    Missing {coverage.asset_type} symbols ({coverage.missing_symbols.length})
                  </summary>
                  <ul className="small">
                    {coverage.missing_symbols.map((missing) => (
                      <li key={missing.ticker}>
                        <strong>{missing.ticker}</strong>: {missing.detail || missing.reason.replaceAll('_', ' ')}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ))}
        </div>
      ) : latestScan ? (
        <p className="muted small">
          Coverage details were not recorded for this scan. Full coverage and missing-symbol reasons cannot be verified.
        </p>
      ) : (
        <p className="muted small">No scan has been saved yet. Run a scan to check coverage and candidates.</p>
      )}

      {staleScan ? (
        <p className="small warning" role="status" data-testid="stale-scan-banner">
          Last scan is {formatMinutes(scanAge)} old. Prices and candidates are historical snapshots.
          Run a scan while the app is open to refresh them.
        </p>
      ) : null}

      {!compactDiagnostics && safetyActive ? (
        <p className="system-health-safety-alert small negative" role="status">
          {killSwitchOn ? 'Kill switch is on. ' : ''}
          {breakerOpen ? 'Circuit breaker is open. ' : ''}
          Paper actions may be blocked until safety clears.
        </p>
      ) : null}

      {dataQualityDegraded ? (
        <p
          className="system-health-data-alert small warning"
          role="status"
          data-testid="data-quality-banner"
        >
          {stockBars.tone === 'bad' || stockBars.tone === 'warning' ? 'Stock bars are stale. ' : ''}
          {cryptoBars.tone === 'bad' || cryptoBars.tone === 'warning' ? 'Crypto bars are stale. ' : ''}
          {qualityFlags.length ? `Recorded data-quality flags: ${qualityFlags.join('; ')}. ` : ''}
          {provider.tone === 'bad' ? 'The last scan recorded a critical provider status. ' : ''}
          Affected signals may be unreliable.
        </p>
      ) : null}

      <details className="ui-disclosure system-health-details">
        <summary className="ui-disclosure-summary muted small">Health details</summary>
        <div className="system-health-details-grid">
          {latestScan?.market_status ? (
            <MarketStatusBadge status={latestScan.market_status} />
          ) : (
            <StatusPill label="Market" value="unknown" tone="muted" />
          )}
          <StatusPill
            label="Backend"
            value={backendOk ? 'OK' : 'down'}
            tone={backendOk ? 'ok' : 'bad'}
          />
          <StatusPill
            label="Worker"
            value={workerRunning ? 'running' : 'stopped'}
            tone={workerRunning ? 'ok' : 'warning'}
          />
          <StatusPill
            label="Scheduler"
            value={schedulerEnabled ? 'on' : 'off'}
            tone={schedulerEnabled ? 'ok' : 'warning'}
          />
          <StatusPill
            label="Last scan"
            value={formatMinutes(scanAge)}
            tone={scanAge == null ? 'muted' : scanAge > SCAN_FRESH_MAX_MINUTES ? 'warning' : 'ok'}
          />
          <StatusPill
            label="Kill switch"
            value={killSwitchOn ? 'on' : 'off'}
            tone={killSwitchOn ? 'bad' : 'ok'}
          />
          <StatusPill
            label="Breaker"
            value={breakerState}
            tone={breakerOpen ? 'bad' : breakerState === 'unknown' ? 'muted' : 'ok'}
          />
        </div>
        {systemReadiness.reasons.length ? (
          <p className="muted small" style={{ margin: '8px 0 0' }}>
            {systemReadiness.reasons.join(' · ')}
          </p>
        ) : null}
      </details>
    </section>
  );
}
