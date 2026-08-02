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
  hasBadFreshnessFlags as hasBadRowFreshnessFlags,
  SCAN_FRESH_MAX_MINUTES,
} from '@/lib/freshness';

type StatusTone = 'ok' | 'warning' | 'bad' | 'muted';
const SEVERE_STALE_MINUTES = 360;

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function ageFromTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, Math.round((Date.now() - timestamp) / 60_000));
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

function rowHasBadFreshnessFlags(row: Pick<ScanResult, 'freshness_flags'>): boolean {
  return hasBadRowFreshnessFlags(row.freshness_flags);
}

function rowBarAge(row: Pick<ScanResult, 'bar_age_minutes'>): number | null {
  return finiteNumber(row.bar_age_minutes);
}

function hasBadFreshnessFlags(latestScan: ScanRun | null): boolean {
  return (latestScan?.results ?? []).some((row) => rowHasBadFreshnessFlags(row));
}

function barsState(latestScan: ScanRun | null): { label: string; tone: StatusTone } {
  const ages = (latestScan?.results ?? [])
    .map((row) => finiteNumber(row.bar_age_minutes))
    .filter((age): age is number => age != null);
  const badFlags = hasBadFreshnessFlags(latestScan);

  if (!ages.length) {
    return badFlags
      ? { label: 'flags stale', tone: 'warning' }
      : { label: 'unknown', tone: 'muted' };
  }

  const maxAge = Math.max(...ages);
  if (maxAge > 1440) return { label: '>24h stale', tone: 'bad' };
  if (maxAge > 360) return { label: '>6h stale', tone: 'bad' };
  if (maxAge > 120) return { label: '>120m stale', tone: 'warning' };
  if (maxAge > FRESH_BAR_MAX_MINUTES || badFlags) return { label: 'stale', tone: 'warning' };
  return { label: 'fresh', tone: 'ok' };
}

function rowSeverelyStale(row: ScanResult): boolean {
  const age = rowBarAge(row);
  return (age != null && age > SEVERE_STALE_MINUTES) || rowHasBadFreshnessFlags(row);
}

function rowUnusableOrStale(row: ScanResult): boolean {
  const age = rowBarAge(row);
  return age == null || age > FRESH_BAR_MAX_MINUTES || rowHasBadFreshnessFlags(row);
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

/** Provider critical or bars not fresh (stale/warning) means signals may be unreliable. */
function isDataQualityDegraded(
  provider: { tone: StatusTone },
  bars: { tone: StatusTone },
): boolean {
  return provider.tone === 'bad' || bars.tone === 'bad' || bars.tone === 'warning';
}

/**
 * Downgrade a PASS to WARN when market-data quality is degraded so the System pill
 * never contradicts a critical Provider / stale Bars pill. FAIL always wins.
 */
function applyDataQualityWarning(
  summary: SystemReadinessSummary,
  provider: { tone: StatusTone },
  bars: { tone: StatusTone },
): SystemReadinessSummary {
  if (summary.status !== 'PASS') return summary;
  if (!isDataQualityDegraded(provider, bars)) return summary;
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
}: {
  health: HealthResponse | null;
  automation: AutomationStatusResponse | null;
  latestScan: ScanRun | null;
  systemReadiness?: SystemReadinessResponse | null;
}) {
  const backendOk = health?.ok === true;
  const scanAge =
    finiteNumber(health?.last_scan_age_minutes) ?? ageFromTimestamp(latestScan?.created_at);
  const provider = providerState(latestScan);
  const bars = barsState(latestScan);
  const schedulerEnabled = health?.scheduler_enabled === true;
  const workerRunning = health?.worker_alive ?? (health?.scheduler_running === true);
  const killSwitchOn = automation?.kill_switch_enabled === true;
  const breakerState = automation?.breaker?.state ?? 'unknown';
  const breakerOpen = breakerState === 'open';
  const baseReadiness =
    summarizeServerReadiness(serverReadiness) ??
    computeSystemReadiness({ health, automation, latestScan });
  const systemReadiness = applyDataQualityWarning(baseReadiness, provider, bars);
  const safetyActive = killSwitchOn || breakerOpen;
  const dataQualityDegraded = isDataQualityDegraded(provider, bars);

  return (
    <section className="system-health-banner" aria-label="Dashboard status">
      <div className="system-health-primary" data-testid="system-health-primary">
        <StatusPill
          label="Paper"
          value={automation?.dry_run_only === false ? 'check' : 'dry-run only'}
          tone={automation?.dry_run_only === false ? 'bad' : 'ok'}
          title="Paper mode and dry-run only; no live trading"
        />
        <StatusPill
          label="System"
          value={systemReadiness.status}
          tone={systemReadiness.tone}
          title={systemReadiness.reasons.join('; ')}
        />
        <StatusPill label="Provider" value={provider.label} tone={provider.tone} />
        <StatusPill label="Bars" value={bars.label} tone={bars.tone} />
        <StatusPill
          label="Real-money trust"
          value={health?.trust_evidence_ready === true ? 'evidence ready' : 'blocked'}
          tone={health?.trust_evidence_ready === true ? 'ok' : 'muted'}
          title={
            'Real-money trust stays blocked until live paper-forward and out-of-sample evidence clears thresholds. Paper dry-run is unaffected.'
          }
        />
      </div>

      {safetyActive ? (
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
          Market data is stale or provider is critical. Signals may be unreliable until fresh
          data is available.
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
