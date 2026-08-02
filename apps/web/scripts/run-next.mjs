#!/usr/bin/env node
/**
 * Cross-platform launcher for the Next.js CLI that normalizes the Windows
 * drive-letter casing BEFORE Next starts.
 *
 * Why: Next.js / webpack resolve module paths from several sources -
 * `process.cwd()`, the resolved `next` bin path, and `process.env.PWD`. On
 * Windows these can disagree on the drive-letter case: here `process.cwd()` and
 * the `next` bin resolve as lowercase (`c:\...`) while `process.env.PWD` is
 * uppercase (`C:/...`). webpack then sees the same files under two identifiers
 * and bundles TWO copies of React; the duplicate copy has a null internal
 * dispatcher, which crashes the pages-router /_error (/404, /500) prerender
 * during `next build` with "Cannot read properties of null (reading
 * 'useContext')". Aligning `PWD` to the exact casing of `process.cwd()` (the
 * casing the bin resolution also uses) makes every source consistent and removes
 * the duplication at the source - no masking of real errors.
 *
 * On non-Windows platforms this is a transparent passthrough.
 */
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

if (process.platform === 'win32') {
  // Do NOT chdir: changing cwd casing alone reintroduces the mismatch because
  // the resolved `next` bin path keeps its original casing. Instead align PWD to
  // cwd's actual casing so all path sources agree.
  process.env.PWD = process.cwd();
}

const nextBin = require.resolve('next/dist/bin/next');
const args = process.argv.slice(2);

const child = spawn(process.execPath, [nextBin, ...args], {
  stdio: 'inherit',
  cwd: process.cwd(),
  env: process.env,
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
