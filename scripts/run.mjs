// Runs one command inside client/, server/ or e2e/ with the repo-root `.env` loaded (see
// `load-env.mjs`). Used by the root package.json, which has no dependencies and only runs scripts:
//   node scripts/run.mjs server uv run python -m silverloop.demo_story
// Arguments reach the command exactly as given (`pnpm test:postgres -k "a and b"` passes
// `a and b` as one argument; with pnpm 11 put extra arguments straight after the script name, no
// `--`): there is no shell on POSIX to re-split or expand them.
import { spawn } from 'node:child_process';
import { join } from 'node:path';

import { loadRootEnv, repoRoot } from './load-env.mjs';

const [folder, ...command] = process.argv.slice(2);
if (!['client', 'server', 'e2e'].includes(folder) || command.length === 0) {
  console.error('usage: node scripts/run.mjs <client|server|e2e> <command> [args...]');
  process.exit(2);
}

loadRootEnv();

const options = { cwd: join(repoRoot, folder), stdio: 'inherit', env: process.env };
let child;
if (process.platform === 'win32') {
  // `pnpm` (and often `uv`) are .cmd shims on Windows, which only start through cmd.exe. Each
  // argument is quoted for it so spaces and cmd's & | < > ^ ( ) stay part of the argument; a `"`
  // inside is doubled and trailing backslashes are doubled so the quote still closes. cmd still
  // expands %NAME% inside quotes, so arguments containing % are not safe on Windows.
  const quote = (arg) =>
    /^[\w./:=@+,-]+$/.test(arg) ? arg : `"${arg.replaceAll('"', '""').replace(/(\\+)$/, '$1$1')}"`;
  child = spawn(command.map(quote).join(' '), { ...options, shell: true });
} else {
  child = spawn(command[0], command.slice(1), options);
}

child.on('error', (error) => {
  console.error(`Could not start "${command[0]}" in ${folder}/: ${error.message}`);
  process.exit(1);
});
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));

// Ctrl-C reaches the child directly (same process group). A TERM or HUP sent to this script alone
// (a closed terminal, `kill`) is passed on, so pytest, Playwright or uv are not left running.
for (const signal of ['SIGTERM', 'SIGHUP']) {
  process.on(signal, () => {
    if (child.exitCode === null && child.signalCode === null) child.kill(signal);
  });
}
