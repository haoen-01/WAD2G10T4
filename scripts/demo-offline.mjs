// Starts the API (SQLite, fixture data, no LLM, sign-in off) and the web app together, with no
// credentials: http://127.0.0.1:3000 for the app, http://127.0.0.1:8000 for the API.
//
// This is a Node script rather than `VAR=value node ...` in package.json because that syntax fails
// in the default Windows shell. It sets the offline environment and runs `scripts/dev.mjs` (the
// same runner as `pnpm dev`), which starts the web app from client/ and the API from server/.
//
// Before starting, it checks the things that most often stop a first run, and says how to fix
// them in plain words, instead of leaving only a failed `api` line to read:
//   1. The web app's JavaScript packages must be installed (client/node_modules).
//   2. `uv` (the Python tool the API runs through) must be installed and on the PATH.
//   3. The API's Python packages must be installed. If they are missing, it runs `uv sync` itself.
//
// `--agent` (`pnpm demo:agent`) also turns the outreach planner on, replaying the committed
// synthetic recording (`server/recordings/demo-planner.json`) instead of calling any model, so
// nothing is sent anywhere. Remake it with `uv run python -m silverloop.agent.demo_recording record`.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const clientDirectory = join(repoRoot, 'client');
const serverDirectory = join(repoRoot, 'server');
const agentDemo = process.argv.includes('--agent');
const recording = join(serverDirectory, 'recordings', 'demo-planner.json');

function stop(lines) {
  console.error(`\n${lines.join('\n')}\n`);
  process.exit(1);
}

const nodeMajor = Number(process.versions.node.split('.')[0]);
if (nodeMajor !== 24) {
  console.warn(
    `\nWarning: this project expects Node 24, but this terminal has Node ${process.versions.node}.` +
      '\nIf anything below fails, install Node 24 LTS from https://nodejs.org and reopen the terminal.\n',
  );
}

if (!existsSync(join(clientDirectory, 'node_modules'))) {
  stop([
    'The web app’s JavaScript packages are not installed yet.',
    'Run this from the project folder, then try again:',
    '  pnpm --dir client install',
  ]);
}

const uv = spawnSync('uv', ['--version'], { shell: true, encoding: 'utf8' });
if (uv.status !== 0) {
  stop([
    'The API needs "uv", but this terminal cannot find it.',
    'Install it, then close and reopen the terminal (or VS Code) and try again:',
    '  Windows (PowerShell):  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
    '  macOS / Linux:         curl -LsSf https://astral.sh/uv/install.sh | sh',
  ]);
}

if (!existsSync(join(serverDirectory, '.venv'))) {
  console.log('Installing the API’s Python packages (first run only, about a minute)…');
  const sync = spawnSync('uv', ['sync'], { cwd: serverDirectory, stdio: 'inherit', shell: true });
  if (sync.status !== 0) {
    stop([
      'Installing the API’s Python packages failed (see the message above).',
      'If it says Python 3.13 is missing, run these and try again:',
      '  cd server',
      '  uv python install 3.13',
      '  uv sync',
    ]);
  }
}

// SQLite will not create the folder for its own file, and the API runs from server/.
mkdirSync(join(serverDirectory, '.demo'), { recursive: true });

const child = spawn(process.execPath, [join(repoRoot, 'scripts', 'dev.mjs')], {
  stdio: 'inherit',
  env: {
    ...process.env,
    CAREPLUS_RUNTIME_PROFILE: 'offline',
    SILVERLOOP_RUNTIME_PROFILE: 'offline',
    DATABASE_URL: 'sqlite+pysqlite:///./.demo/silverloop.db',
    ADAPTER_MODE: 'fixture',
    LLM_ENABLED: agentDemo ? 'true' : 'false',
    ...(agentDemo
      ? {
          LLM_PROVIDER: 'recorded',
          LLM_RECORDING_PATH: recording,
          LLM_MODEL: 'synthetic-scripted-stand-in-v1',
        }
      : {}),
    AUTH_ENABLED: 'false',
    VITE_AUTH_ENABLED: 'false',
  },
});

child.on('exit', (code) => process.exit(code ?? 1));
