import '@testing-library/jest-dom/vitest';
import dns from 'node:dns';
import net from 'node:net';
import tls from 'node:tls';
import { afterEach, expect } from 'vitest';

// Tests supply fake providers/fetch. Keep this guard outside vi.spyOn so a
// suite's restoreAllMocks cannot re-enable real network access.
const networkAttempts: string[] = [];
function blockedNetwork(kind: string): never {
  networkAttempts.push(kind);
  throw new Error(`External network blocked in tests: ${kind}`);
}
globalThis.fetch = async () => blockedNetwork('fetch');
net.Socket.prototype.connect = () => blockedNetwork('socket.connect');
tls.connect = () => blockedNetwork('tls.connect');
dns.lookup = Object.assign(() => blockedNetwork('dns.lookup'), {
  __promisify__: async () => blockedNetwork('dns.lookup'),
});
dns.promises.lookup = async () => blockedNetwork('dns.promises.lookup');

afterEach(() => {
  const attempts = networkAttempts.splice(0);
  expect(attempts, 'No unmocked network attempts are permitted').toEqual([]);
});
