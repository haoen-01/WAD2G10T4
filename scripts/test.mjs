// `pnpm test`: the API suite, the web unit tests and the Playwright suite, one after another.
// Every suite runs even when an earlier one fails (as the former Nx `run-many` did), and this
// exits non-zero if any failed. One at a time on purpose: run concurrently, the CPU-bound API suite
// starves the browser suite's dev servers on a small CI runner. Each runs through `run.mjs` (root
// `.env` loaded).
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';

import { repoRoot } from './load-env.mjs';

const SUITES = [
  { name: 'API (pytest)', args: ['server', 'uv', 'run', 'pytest'] },
  { name: 'web unit tests', args: ['client', 'pnpm', 'test'] },
  { name: 'browser (Playwright)', args: ['e2e', 'pnpm', 'test'] },
];

const runScript = join(repoRoot, 'scripts', 'run.mjs');
const results = SUITES.map(({ name, args }) => {
  console.log(`\n=== ${name} ===`);
  const run = spawnSync(process.execPath, [runScript, ...args], { stdio: 'inherit' });
  return { name, status: run.status ?? 1 };
});

console.log('\n=== Test summary ===');
for (const { name, status } of results) {
  console.log(`${status === 0 ? 'passed' : `FAILED (exit ${status})`}  ${name}`);
}
process.exit(results.some(({ status }) => status !== 0) ? 1 : 0);
