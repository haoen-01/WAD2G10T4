#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_dir/.uv-cache}"

(
  cd "$repo_dir/apps/api"
  uv run python -m silverloop.openapi
)

cd "$repo_dir"
pnpm exec openapi-ts \
  -i ./openapi/silverloop.json \
  -o ./libs/api-client/src/generated
