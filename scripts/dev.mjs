// Runs the Care+ dev servers from the repo root, with no task runner and no dependencies:
//   node scripts/dev.mjs        web (http://127.0.0.1:3000) and API (http://127.0.0.1:8000)
//   node scripts/dev.mjs web    the Vue app only, from client/
//   node scripts/dev.mjs api    the API only, from server/ (runtime check, migrate, then uvicorn)
//
// When two run together, each line is prefixed with its name, and if one stops the other is
// stopped too, so a failed API start is never hidden behind a web server that keeps running.
// `scripts/demo-offline.mjs` runs this script with the offline environment set.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { loadRootEnv, repoRoot } from './load-env.mjs';

const SERVERS = {
  web: {
    cwd: join(repoRoot, 'client'),
    command: 'pnpm dev',
    installed: join(repoRoot, 'client', 'node_modules'),
    missing: 'The web app’s JavaScript packages (client/node_modules) are not installed.',
  },
  api: {
    cwd: join(repoRoot, 'server'),
    command:
      'uv run python -m silverloop.runtime check && uv run alembic upgrade head && ' +
      'uv run uvicorn silverloop.main:app --reload --host 127.0.0.1 --port 8000',
    // No install check: `uv run` creates and syncs the environment itself, wherever uv keeps it
    // (server/.venv, or UV_PROJECT_ENVIRONMENT).
    installed: null,
  },
};

const requested = process.argv.slice(2);
const names = requested.length > 0 ? requested : ['web', 'api'];
for (const name of names) {
  if (!(name in SERVERS)) {
    console.error(`Unknown server "${name}". Use one of: ${Object.keys(SERVERS).join(', ')}.`);
    process.exit(2);
  }
}

// `pnpm run setup`, not `pnpm setup`: the bare form can mean pnpm's own built-in command.
const notInstalled = names.filter(
  (name) => SERVERS[name].installed && !existsSync(SERVERS[name].installed),
);
if (notInstalled.length > 0) {
  console.error(
    `\n${notInstalled.map((name) => SERVERS[name].missing).join('\n')}\n` +
      'Run this from the project folder first, then try again:\n  pnpm run setup\n',
  );
  process.exit(1);
}

// The repo-root `.env`, as Nx used to load it for `dev`; variables already set (the offline
// demo's) win.
loadRootEnv();

const prefixed = names.length > 1;
const isWindows = process.platform === 'win32';
// Children that have not yet closed (exited, and their output fully drained).
const running = new Map();
let exitCode = null;
let killTimer = null;

function pipe(stream, target, name) {
  let buffered = '';
  stream.setEncoding('utf8');
  stream.on('data', (chunk) => {
    buffered += chunk;
    const lines = buffered.split('\n');
    buffered = lines.pop() ?? '';
    for (const line of lines) target.write(`${name}: ${line}\n`);
  });
  stream.on('end', () => {
    if (buffered) target.write(`${name}: ${buffered}\n`);
  });
}

// Run together, each server is its own process group (a shell plus uv/uvicorn or pnpm/vite), so
// stopping one stops everything it started rather than leaving an orphan holding its port. The
// group is signalled even after its shell has exited, in case something it started lives on.
function signalChild(child, signal) {
  if (child.pid === undefined) return;
  if (isWindows) {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    return;
  }
  try {
    process.kill(prefixed ? -child.pid : child.pid, signal);
  } catch {
    // Already gone.
  }
}

function stopAll() {
  for (const child of running.values()) signalChild(child, 'SIGTERM');
  // A server that ignores SIGTERM for 10 seconds is killed, so this script always finishes.
  if (killTimer === null && running.size > 0) {
    killTimer = setTimeout(() => {
      for (const child of running.values()) signalChild(child, 'SIGKILL');
    }, 10_000);
    killTimer.unref();
  }
}

function finish(code) {
  if (exitCode === null) exitCode = code;
  stopAll();
}

for (const name of names) {
  const { cwd, command } = SERVERS[name];
  const child = spawn(command, {
    cwd,
    shell: true,
    env: process.env,
    // Run alone, a server owns the terminal as usual. Run together, each gets its own process
    // group (so it can be stopped as a whole) and no stdin (a background group reading the
    // terminal would be suspended).
    detached: prefixed && !isWindows,
    stdio: prefixed ? ['ignore', 'pipe', 'pipe'] : 'inherit',
  });
  if (prefixed) {
    pipe(child.stdout, process.stdout, name);
    pipe(child.stderr, process.stderr, name);
  }
  running.set(name, child);
  child.on('exit', (code, signal) => {
    if (exitCode === null && prefixed) {
      console.error(`${name} stopped (${signal ?? `exit code ${code}`}).`);
    }
    finish(code ?? (signal ? 1 : 0));
  });
  // 'close' comes after 'exit', once the child's output has been read to the end, so the last
  // lines a crashing server prints (usually the error itself) are written before this exits.
  child.on('close', (code, signal) => {
    running.delete(name);
    finish(code ?? (signal ? 1 : 0));
    if (running.size === 0) process.exit(exitCode ?? 0);
  });
}

// Ctrl-C, `kill`, and closing the terminal or editor tab (SIGHUP) all stop both servers; the
// servers run in their own process groups, so nothing else would reach them.
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => finish(0));
}
// Any other way out of this process (an uncaught error included) still stops the servers.
process.on('exit', () => {
  for (const child of running.values()) signalChild(child, 'SIGTERM');
});
