// Loads the repo-root `.env` into this process's environment, if the file exists, without
// overriding variables that are already set. The root scripts that run the API, its CLI commands
// and the test suites go through this (via `scripts/run.mjs` and `scripts/dev.mjs`) so commands
// that read the environment directly -- `pnpm demo:story`'s Supabase keys, the runtime check's
// `ANTHROPIC_API_KEY` / `AWS_REGION`, a `SILVERLOOP_POSTGRES_TEST_URL` for `pnpm test:postgres` --
// see the same values they did when Nx loaded `.env` for every task. With no `.env` (the offline
// demo, CI) nothing is loaded and nothing fails.
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

export function loadRootEnv() {
  const envFile = join(repoRoot, '.env');
  if (existsSync(envFile)) process.loadEnvFile(envFile);
}
