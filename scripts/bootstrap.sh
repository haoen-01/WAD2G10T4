#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

for required_command in node pnpm python3 uv; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "Missing required command: $required_command" >&2
    exit 1
  fi
done

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from the credential-free Supabase template."
fi

# client/, e2e/ and server/ are separate installs; the root package.json only runs scripts.
pnpm --dir client install --frozen-lockfile
pnpm --dir e2e install --frozen-lockfile
# Shared git hooks: rejects commits authored or co-authored by Claude (CONTRIBUTING.md). Set here
# because the root has no install, so its `prepare` script never runs on its own.
git config core.hooksPath .githooks
pnpm --dir e2e exec playwright install chromium
uv --directory server sync --frozen

echo "Care+ setup complete. Replace the Supabase DATABASE_URL in .env, then run: pnpm dev"
echo "For the credential-free emergency fallback, run: pnpm demo:offline"
