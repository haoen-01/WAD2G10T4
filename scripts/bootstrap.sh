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

# A pnpm-workspace.yaml at the root turns client/ and e2e/ into parts of one root project, so their
# installs report "Already up to date" and install nothing. pnpm 11 writes one there when it blocks
# a build script, e.g. after a pull from the old layout with its root node_modules still present.
if [[ -f pnpm-workspace.yaml ]]; then
  echo "Found pnpm-workspace.yaml at the project root, left over from the old layout." >&2
  echo "Delete it (and the old root node_modules, apps/, libs/ and .nx folders), then run setup again." >&2
  exit 1
fi

# client/, e2e/ and server/ are separate installs; the root package.json only runs scripts.
pnpm --dir client install --frozen-lockfile
pnpm --dir e2e install --frozen-lockfile
pnpm --dir e2e exec playwright install chromium
uv --directory server sync --frozen

echo "Care+ setup complete. Replace the Supabase DATABASE_URL in .env, then run: pnpm dev"
echo "For the credential-free emergency fallback, run: pnpm demo:offline"
