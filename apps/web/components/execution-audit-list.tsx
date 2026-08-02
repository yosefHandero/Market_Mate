import type { ExecutionAuditSummary } from '@/lib/types';

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

export function ExecutionAuditList({ audits }: { audits: ExecutionAuditSummary[] }) {
  const visibleAudits = audits.slice(0, 25);

  return (
    <section className="card execution-audit-list" aria-label="Recent dry-run audits">
      <h2 className="proof-section-title">Recent dry-run audits</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {audits.length ? `${audits.length} recent rows` : 'No audits yet'}
      </p>
      {visibleAudits.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Ticker</th>
                <th>Side</th>
                <th>Status</th>
                <th>Signal</th>
                <th>Gate</th>
                <th>Dry run</th>
              </tr>
            </thead>
            <tbody>
              {visibleAudits.map((audit) => (
                <tr key={audit.id}>
                  <td>{formatDateTime(audit.created_at)}</td>
                  <td>{audit.ticker}</td>
                  <td>{audit.side}</td>
                  <td>{audit.lifecycle_status}</td>
                  <td>{audit.latest_signal ?? '--'}</td>
                  <td>{audit.trade_gate_allowed === false ? 'blocked' : audit.trade_gate_allowed ? 'ok' : '--'}</td>
                  <td>{audit.dry_run ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No dry-run audits recorded yet.</p>
      )}
    </section>
  );
}
