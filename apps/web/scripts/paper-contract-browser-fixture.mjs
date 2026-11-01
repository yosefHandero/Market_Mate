#!/usr/bin/env node
// Offline UI fixture. The real execution/closure logic is tested by isolated Python tests.
// Run: node --experimental-strip-types scripts/paper-contract-browser-fixture.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { getDashboardFixture } from '../tests/fixtures/dashboard-fixture.ts';

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'market-mate-paper-browser-'));
for (const name of ['app', 'components', 'lib', 'package.json', 'next.config.ts', 'tsconfig.json']) {
  fs.cpSync(path.join(webRoot, name), path.join(sandbox, name), { recursive: true });
}
fs.symlinkSync(path.join(webRoot, 'node_modules'), path.join(sandbox, 'node_modules'), 'junction');
const fixture = getDashboardFixture();
const row = fixture.latestScan.results.find((result) => result.ticker === 'NVDA');
row.weekly_prediction = {
  horizon: '1w', horizon_label: '1 week', pattern_name: 'fixture-weekly', directional_bias: 'bullish',
  range_low: 120, range_high: 145, upside_probability_pct: 64, historical_hit_rate_pct: 61,
  avg_forward_1w_return_pct: 1.2, sample_size: 40, data_quality: 'ok', evidence_basis: 'historical_only',
  real_money_trust_blocked: true, pattern_gate_checks: [], methodology: 'fixture', disclaimer: 'Advisory',
};
row.upside_probability_pct = 64;
row.exit_window = {
  expected_growth_window_label: '1 week (7 calendar days; advisory)', expected_growth_days: 7,
  estimated_exit_price: 131, projected_range_low: 120, projected_range_high: 145,
  invalidation_level: 127, invalidation_note: 'Advisory structural level',
  stop_growing_signal: 'Forecast only', stop_growing_conditions: [], risk_warning: 'No guaranteed upside',
  confidence_change_note: 'Historical-only weekly evidence', methodology: 'fixture', disclaimer: 'Advisory',
};
const contract = {
  source_run_id: 'fixture-latest', policy_id: 'hybrid', policy_version: 'fixture-v1', decision_fingerprint: 'fixture-decision',
  holding_horizon: '1h', holding_duration_seconds: 3600, exit_method: 'time_based',
};
const base = {
  id: 1, intent_key: 'fixture-open', execution_audit_id: 44, ticker: 'PENDING', asset_type: 'stock', side: 'buy',
  quantity: 1, simulated_fill_price: 100, notional_usd: 100, cost_basis_usd: 100, close_price: null,
  realized_pnl: null, status: 'open', opened_at: '2026-10-11T14:00:00Z', closed_at: null,
  strategy_version: 'fixture-v1', confidence: 90, ...contract, exit_due_at: '2026-10-11T15:00:00Z',
  contract_status: 'recorded', closure_status: 'overdue_pending_quote', close_delay_seconds: null,
};
const positions = [
  base,
  { ...base, id: 2, intent_key: 'fixture-late', ticker: 'LATE', status: 'closed', close_price: 103, realized_pnl: 3, closed_at: '2026-10-11T15:02:00Z', closure_status: 'closed_late', close_delay_seconds: 120 },
  { ...base, id: 3, intent_key: 'fixture-legacy', ticker: 'LEGACY', source_run_id: null, policy_id: null, policy_version: null, decision_fingerprint: null, holding_horizon: null, holding_duration_seconds: null, exit_method: null, exit_due_at: null, contract_status: 'legacy_unknown', closure_status: 'legacy_unknown' },
];
const requests = [];
let placement;
function summary() {
  return { ...fixture.paperSummary, open_positions: positions.filter((position) => position.status === 'open').length,
    closed_positions: 1, total_count: positions.length, total_realized_pnl: 3, gross_pnl_usd: 3,
    overdue_positions: 1, legacy_unknown_positions: 1, late_closed_positions: 1 };
}
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1:8017');
  let body = '';
  for await (const chunk of request) body += chunk;
  const payload = body ? JSON.parse(body) : null;
  requests.push({ method: request.method, path: url.pathname, payload });
  let data;
  try {
    switch (url.pathname) {
      case '/scan/latest': data = fixture.latestScan; break;
      case '/dashboard/decisions/latest': data = fixture.decisions; break;
      case '/readyz': data = { ...fixture.health, scheduler_enabled: false, scheduler_running: false, worker_alive: false }; break;
      case '/automation/status': data = { ...fixture.automation, kill_switch_enabled: false }; break;
      case '/system/readiness': data = { status: 'PASS', reasons: [], provider: { worst_status: 'ok', critical_count: 0 }, safety_blockers: [] }; break;
      case '/paper/ledger': data = positions; break;
      case '/paper/ledger/summary': data = summary(); break;
      case '/orders/audits': data = []; break;
      case '/proof/summary': data = { generated_at: '2026-10-11T15:02:00Z', ledger: summary(), loop_metrics: { recent_dry_runs: placement ? 1 : 0, recent_previewed: 1, recent_blocked: 0, total_audits: 1 }, last_scan_at: fixture.latestScan.created_at, scan_fresh: true, note: 'Offline fixture; all prices are mocked.' }; break;
      case '/orders/preview':
        assert.equal(payload.ticker, 'NVDA');
        assert.equal(payload.requested_notional_usd, 100);
        assert.equal(payload.qty, undefined);
        assert.equal(payload.stop_price, undefined);
        assert.equal(payload.target_price, undefined);
        data = { broker: 'alpaca', ticker: 'NVDA', side: 'buy', qty: 0.778816, order_type: 'market', notional_estimate: 99.9999744, latest_price: 128.4, time_in_force: 'day', warnings: [], trade_gate: { allowed: true }, execution_audit_id: 60, entry_price: 128.4, stop_price: null, target_price: null, position_size: 0.778816, estimated_pnl_usd: null, gate_result: 'allowed', freshness: 'fresh', reject_reasons: [], paper_contract: contract };
        break;
      case '/orders/place':
        assert.equal(payload.qty, 0.778816);
        assert.equal(payload.requested_notional_usd ?? null, null);
        assert.deepEqual(payload.paper_contract, contract);
        assert.equal(payload.preview_audit_id, 60);
        assert.equal(payload.dry_run, true);
        if (!placement) {
          positions.push({ ...base, id: 4, ticker: 'NVDA', execution_audit_id: 61, intent_key: payload.idempotency_key, quantity: payload.qty, simulated_fill_price: 128.4, notional_usd: 99.9999744, cost_basis_usd: 99.9999744, opened_at: '2026-10-11T15:05:00Z', exit_due_at: '2026-10-11T16:05:00Z', closure_status: 'scheduled' });
          placement = { ok: true, broker: 'alpaca', submitted: false, dry_run: true, message: 'Mocked paper receipt', idempotency_key: payload.idempotency_key, order_id: null, status: 'dry_run', raw: null, trade_gate: null, execution_audit_id: 61, ledger_id: 4, fill_price: 128.4, filled_qty: payload.qty, slippage_assumption_bps: 0, recommended_action_snapshot: 'preview', paper_contract: contract, filled_at: '2026-10-11T15:05:00Z', exit_due_at: '2026-10-11T16:05:00Z' };
        }
        data = placement;
        break;
      case '/fixture/requests': data = requests; break;
      default: response.writeHead(404, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ detail: `Unexpected fixture request: ${url.pathname}` })); return;
    }
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify(data));
  } catch (error) {
    response.writeHead(400, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ detail: String(error) }));
  }
});
server.listen(8017, '127.0.0.1', () => {
  console.log(`Mock scanner http://127.0.0.1:8017; temporary Next source copy ${sandbox}`);
});
const child = spawn(process.execPath, [path.join(webRoot, 'node_modules/next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '--port', '3017'], {
  cwd: sandbox, stdio: 'inherit', windowsHide: true,
  env: { ...process.env, PWD: sandbox, NEXT_PUBLIC_SCANNER_API_BASE: 'http://127.0.0.1:8017', SCANNER_ADMIN_API_TOKEN: 'offline-fixture-admin', SCANNER_READ_API_TOKEN: 'offline-fixture-read', NEXT_TELEMETRY_DISABLED: '1' },
});
function shutdown() { child.kill(); server.close(); }
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
child.on('exit', () => server.close());
