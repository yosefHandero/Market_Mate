// Disposable Next copy: real paper backend :8018; operational health is a fixture.
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { getDashboardFixture } from '../tests/fixtures/dashboard-fixture.ts';
const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'market-mate-release-next-'));
for (const name of ['app', 'components', 'lib', 'package.json', 'next.config.ts', 'tsconfig.json']) fs.cpSync(path.join(webRoot, name), path.join(sandbox, name), { recursive: true });
fs.symlinkSync(path.join(webRoot, 'node_modules'), path.join(sandbox, 'node_modules'), 'junction');
const fixture = getDashboardFixture();
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1:8017');
  let text = ''; for await (const chunk of request) text += chunk;
  let value;
  if (url.pathname === '/readyz') value = { ...fixture.health, scan_fresh: true, scheduler_enabled: false, worker_alive: false };
  if (url.pathname === '/automation/status') value = { ...fixture.automation, kill_switch_enabled: false };
  if (url.pathname === '/system/readiness') value = { status: 'PASS', reasons: [], provider: { worst_status: 'ok', critical_count: 0 }, safety_blockers: [] };
  if (value) { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(value)); return; }
  try {
    const upstream = await fetch(`http://127.0.0.1:8018${request.url}`, { method: request.method, body: text || undefined, headers: { 'Content-Type': 'application/json' } });
    response.writeHead(upstream.status, { 'Content-Type': 'application/json' }); response.end(await upstream.text());
  } catch (error) { response.writeHead(500); response.end(JSON.stringify({ detail: String(error) })); }
});
server.listen(8017, '127.0.0.1');
const child = spawn(process.execPath, [path.join(webRoot, 'node_modules/next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '--port', '3017'], {
  cwd: sandbox, stdio: 'inherit', windowsHide: true,
  env: { ...process.env, PWD: sandbox, NEXT_PUBLIC_SCANNER_API_BASE: 'http://127.0.0.1:8017', SCANNER_ADMIN_API_TOKEN: 'isolated-release-admin', SCANNER_READ_API_TOKEN: 'isolated-release-read', NEXT_TELEMETRY_DISABLED: '1' },
});
console.log(`Isolated release UI http://127.0.0.1:3017; source copy ${sandbox}`);
function shutdown() { child.kill(); server.close(); }
process.on('SIGINT', shutdown); process.on('SIGTERM', shutdown); child.on('exit', () => server.close());
