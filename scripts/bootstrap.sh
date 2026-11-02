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

pnpm install --frozen-lockfile
# Shared git hooks: rejects commits authored or co-authored by Claude (CONTRIBUTING.md).
git config core.hooksPath .githooks
pnpm exec playwright install chromium
(
  cd apps/api
  uv sync --frozen
)

echo "Care+ setup complete. Replace the Supabase DATABASE_URL in .env, then run: pnpm dev"
echo "For the credential-free emergency fallback, run: pnpm demo:offline"
