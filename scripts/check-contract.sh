#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

bash scripts/generate-contract.sh

if ! git diff --exit-code -- openapi/silverloop.json libs/api-client/src/generated; then
  echo "Generated API contract is stale. Run: pnpm client:generate" >&2
  exit 1
fi

untracked="$(git ls-files --others --exclude-standard -- \
  openapi/silverloop.json libs/api-client/src/generated)"
if [[ -n "$untracked" ]]; then
  echo "$untracked" >&2
  echo "Generated API contract contains uncommitted files." >&2
  exit 1
fi
