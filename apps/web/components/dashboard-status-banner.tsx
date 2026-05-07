import type { AutomationStatusResponse, HealthResponse, ScanRun } from '@/lib/types';

type StatusTone = 'ok' | 'warning' | 'bad' | 'muted';

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

function hasBadFreshnessFlags(latestScan: ScanRun | null): boolean {
  return (latestScan?.results ?? []).some((row) =>
    Object.values(row.freshness_flags ?? {}).some(
      (value) => String(value).trim().toLowerCase() !== 'ok',
    ),
  );
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
  if (maxAge > 30 || badFlags) return { label: 'stale', tone: 'warning' };
  return { label: 'fresh', tone: 'ok' };
}

function badgeClass(tone: StatusTone): string {
  if (tone === 'ok') return 'badge green';
  if (tone === 'warning') return 'badge amber';
  if (tone === 'bad') return 'badge red';
  return 'badge';
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: StatusTone }) {
  return (
    <span className={badgeClass(tone)} style={{ gap: 6 }}>
      <span className="muted">{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

export function DashboardStatusBanner({
  health,
  automation,
  latestScan,
}: {
  health: HealthResponse | null;
  automation: AutomationStatusResponse | null;
  latestScan: ScanRun | null;
}) {
  const backendOk = health?.ok === true;
  const scanAge =
    finiteNumber(health?.last_scan_age_minutes) ?? ageFromTimestamp(latestScan?.created_at);
  const provider = providerState(latestScan);
  const bars = barsState(latestScan);
  const schedulerRunning = health?.scheduler_running === true;
  const killSwitchOn = automation?.kill_switch_enabled === true;
  const breakerState = automation?.breaker?.state ?? 'unknown';
  const breakerOpen = breakerState === 'open';

  return (
    <section
      className="detail-panel small"
      aria-label="Dashboard status"
      style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}
    >
      <StatusPill
        label="Backend OK"
        value={backendOk ? 'yes' : 'no'}
        tone={backendOk ? 'ok' : 'bad'}
      />
      <StatusPill
        label="Last scan"
        value={formatMinutes(scanAge)}
        tone={scanAge == null ? 'muted' : scanAge > 30 ? 'warning' : 'ok'}
      />
      <StatusPill label="Provider" value={provider.label} tone={provider.tone} />
      <StatusPill
        label="Scheduler"
        value={schedulerRunning ? 'running' : 'stopped'}
        tone={schedulerRunning ? 'ok' : 'warning'}
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
      <StatusPill label="Bars" value={bars.label} tone={bars.tone} />
    </section>
  );
}
