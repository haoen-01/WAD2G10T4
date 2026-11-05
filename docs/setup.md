# Local setup

## Supported toolchain

- Node.js 24.x (`.nvmrc`)
- pnpm 11.x (pinned in `package.json`)
- Python 3.13.x (`.python-version`)
- uv 0.12 or newer

Supabase PostgreSQL is required for the standard shared-development command. Docker is optional and
is useful only for running the PostgreSQL integration test locally. A cloud database, Healthy 365
account and LLM key are not required for tests or the offline demo.

## First run

```bash
git clone https://github.com/haoen-01/WAD2G10T4.git
cd WAD2G10T4
pnpm run setup
# Replace the placeholder DATABASE_URL in .env with the server-side Session pooler URL.
pnpm dev
```

The setup script creates `.env` only when it does not already exist. The committed value is a
credential-free Supabase placeholder: `pnpm dev` will reject it until it is replaced in the local
file. The script also installs `client/` and `e2e/` from their frozen pnpm lockfiles, the pinned
Chromium browser (through `e2e/`) and the frozen Python environment in `server/`. The root
`package.json` has no dependencies; it only runs scripts. Setup does not download private data or
configure external adapters.

Open <http://127.0.0.1:3000> for the demo and <http://127.0.0.1:8000/docs> for API exploration.

The "Read my day" Kokoro voice is optional and not installed by setup. To use it, run
`uv --directory server sync --group tts`, then once
`uv --directory server run python -m silverloop.tts download`; without it the browser reads aloud
with its own voice. See [read-my-day-voice.md](read-my-day-voice.md).

## Moving an existing checkout to the client/server layout

If your checkout predates the `client/`, `server/` and `e2e/` split, first delete the folders and
files the old layout left behind (they are ignored by git, so pulling does not remove them), then
run setup again. A leftover root `pnpm-workspace.yaml` in particular makes the `e2e/` install
report "Already up to date" without installing Playwright.

PowerShell:

```powershell
Remove-Item -Recurse -Force node_modules, apps, libs, .nx, pnpm-lock.yaml, pnpm-workspace.yaml -ErrorAction SilentlyContinue
pnpm run setup
```

Git Bash, macOS or Linux:

```bash
rm -rf node_modules apps libs .nx pnpm-lock.yaml pnpm-workspace.yaml
pnpm run setup
```

## Separate terminals

If the combined process output is inconvenient:

```bash
pnpm dev:api
pnpm dev:web
```

`pnpm dev:api` performs the same Supabase-first preflight as `pnpm dev`. It rejects missing,
placeholder and SQLite connection strings before running migrations.

## Offline demo

```bash
pnpm demo:offline
```

This command explicitly selects SQLite, fixture adapters and `LLM_ENABLED=false`. It does not read
or overwrite the Supabase `DATABASE_URL` in `.env`. Standard `pnpm dev` never silently falls back to
SQLite.

## Environment contract

The committed `.env.example` contains no credential. Store the real Supabase URL only in the local
`.env` or deployment secret store. Keep `CAREPLUS_RUNTIME_PROFILE=shared`,
`ADAPTER_MODE=fixture` and `LLM_ENABLED=false` for the shared synthetic demo.
`VITE_API_BASE_URL` is intentionally public (Vite ships every `VITE_*` variable to the browser) and
may contain only a FastAPI origin, never a database URL or credential.

## Reset and verification

```bash
pnpm demo:reset   # requires the API to be running
pnpm test:e2e     # real browser + temporary SQLite API
pnpm test:postgres # requires SILVERLOOP_POSTGRES_TEST_URL and a database named with "test"
pnpm demo:supabase-smoke # writes one clearly labelled synthetic scenario to Supabase
pnpm verify       # full static, test, scenario and build gate
```

If ports 3000 or 8000 are busy, stop the existing process before the presentation; changing ports
requires updating both the API CORS origin and `VITE_API_BASE_URL`.

## Deployment

Care+ deploys to Vercel as two projects:

- **API:** root directory `server/`. Vercel serves `app` from `server/index.py`. Set
  `DATABASE_URL` (the Session pooler URL), `SUPABASE_URL`, `AUTH_ENABLED=true` and `CORS_ORIGINS`
  (the client's origin) as environment variables. A deploy of `server/` alone does not include
  `infra/`, so check `GET /ready` afterwards; see [supabase.md](supabase.md#row-level-security).
- **Client:** root directory `client/`, built with `vite build`. `client/vercel.json` rewrites every
  path to `index.html` so the Vue router handles deep links. Set `VITE_API_BASE_URL` to the API's
  origin and the public `VITE_AUTH_ENABLED`, `VITE_SUPABASE_URL` and
  `VITE_SUPABASE_PUBLISHABLE_KEY`.
