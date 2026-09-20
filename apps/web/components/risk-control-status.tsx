import { MarketStatusBadge } from '@/components/market-status-badge';
import type {
  AutomationStatusResponse,
  HealthResponse,
  MarketStatus,
  SystemReadinessResponse,
} from '@/lib/types';

function badgeClass(tone: 'ok' | 'warning' | 'bad' | 'muted'): string {
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
  tone: 'ok' | 'warning' | 'bad' | 'muted';
  title?: string;
}) {
  return (
    <span className={badgeClass(tone)} style={{ gap: 6 }} title={title}>
      <span className="muted">{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

export function RiskControlStatus({
  health,
  automation,
  systemReadiness,
  marketStatus,
}: {
  health: HealthResponse | null;
  automation: AutomationStatusResponse | null;
  systemReadiness: SystemReadinessResponse | null;
  marketStatus?: MarketStatus | null;
}) {
  const liveTradingDisabled = automation?.dry_run_only !== false;
  const killSwitchOn = automation?.kill_switch_enabled === true;
  const breakerOpen = automation?.breaker?.state === 'open';
  const scanFresh = health?.scan_fresh;
  const providerWorst = systemReadiness?.provider?.worst_status ?? 'unknown';
  const providerCritical = (systemReadiness?.provider?.critical_count ?? 0) > 0;

  return (
    <section className="card risk-control-status" aria-label="Risk control status">
      <h2 className="proof-section-title">Risk controls</h2>
      <div className="risk-control-grid">
        <StatusPill
          label="Broker submission"
          value="removed"
          tone="ok"
          title="Paper-only build: there is no broker order-submission code. EXECUTION_ENABLED / ALLOW_LIVE_TRADING are forbidden and cause startup failure."
        />
        <StatusPill
          label="Paper mode"
          value={liveTradingDisabled ? 'on' : 'check'}
          tone={liveTradingDisabled ? 'ok' : 'bad'}
        />
        <StatusPill
          label="Kill switch"
          value={killSwitchOn ? 'on' : 'off'}
          tone={killSwitchOn ? 'bad' : 'ok'}
        />
        <StatusPill
          label="Breaker"
          value={automation?.breaker?.state ?? 'unknown'}
          tone={breakerOpen ? 'bad' : 'ok'}
        />
        <StatusPill
          label="Scan fresh"
          value={scanFresh == null ? 'unknown' : scanFresh ? 'yes' : 'stale'}
          tone={scanFresh == null ? 'muted' : scanFresh ? 'ok' : 'warning'}
        />
        <StatusPill
          label="Provider"
          value={scanFresh === false ? `${providerWorst} (last scan)` : providerWorst}
          tone={providerCritical ? 'bad' : providerWorst === 'degraded' ? 'warning' : providerWorst === 'unknown' || scanFresh !== true ? 'muted' : 'ok'}
          title="Provider status observed during the last scan."
        />
        {marketStatus ? (
          <MarketStatusBadge status={marketStatus} />
        ) : (
          <StatusPill label="Market" value="unknown" tone="muted" />
        )}
      </div>
      {systemReadiness?.safety_blockers?.length ? (
        <p className="negative small" style={{ marginTop: 8 }}>
          Safety blockers: {systemReadiness.safety_blockers.join(' · ')}
        </p>
      ) : null}
    </section>
  );
}
