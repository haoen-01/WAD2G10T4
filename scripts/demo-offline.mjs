// Starts the API (SQLite, fixture data, no LLM, sign-in off) and the web app together, with no
// credentials: http://127.0.0.1:3000 for the app, http://127.0.0.1:8000 for the API.
//
// This is a Node script rather than `VAR=value nx ...` in package.json because that syntax fails
// in the default Windows shell.
//
// Before starting, it checks the two things that most often stop a first run, and says how to fix
// them in plain words, instead of leaving Nx to show only a red cross next to `api:dev`:
//   1. `uv` (the Python tool the API runs through) must be installed and on the PATH.
//   2. The API's Python packages must be installed. If they are missing, it runs `uv sync` itself.
//
// `--agent` (`pnpm demo:agent`) also turns the outreach planner on, replaying the committed
// synthetic recording (`apps/api/recordings/demo-planner.json`) instead of calling any model, so
// nothing is sent anywhere. Remake it with `uv run python -m silverloop.agent.demo_recording record`.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const agentDemo = process.argv.includes('--agent');
const recording = resolve('apps/api/recordings/demo-planner.json');

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

if (!existsSync('node_modules')) {
  stop([
    'The JavaScript packages are not installed yet.',
    'Run this from the project folder, then try again:',
    '  pnpm install',
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

if (!existsSync('apps/api/.venv')) {
  console.log('Installing the API’s Python packages (first run only, about a minute)…');
  const sync = spawnSync('uv', ['sync'], { cwd: 'apps/api', stdio: 'inherit', shell: true });
  if (sync.status !== 0) {
    stop([
      'Installing the API’s Python packages failed (see the message above).',
      'If it says Python 3.13 is missing, run these and try again:',
      '  cd apps/api',
      '  uv python install 3.13',
      '  uv sync',
    ]);
  }
}

// SQLite will not create the folder for its own file, and the API runs from apps/api.
mkdirSync('apps/api/.demo', { recursive: true });

const child = spawn(
  'pnpm',
  ['exec', 'nx', 'run-many', '-t', 'dev', '--projects=web,api', '--parallel=2'],
  {
    stdio: 'inherit',
    shell: true,
    env: {
      ...process.env,
      // Plain scrolling logs instead of Nx's full-screen view, so an error is printed where you
      // can read and copy it, and no background Nx daemon (it can stall in OneDrive folders).
      NX_TUI: 'false',
      NX_DAEMON: 'false',
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
  },
);

child.on('exit', (code) => process.exit(code ?? 1));
