#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

pnpm format:check
pnpm client:check
pnpm lint
pnpm typecheck
pnpm test
pnpm test:scenarios
pnpm evaluate:check
pnpm build

echo "All Care+ verification gates passed."
