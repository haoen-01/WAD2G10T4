#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_dir/.uv-cache}"

(
  cd "$repo_dir/server"
  uv run python -m silverloop.openapi
)

# @hey-api/openapi-ts is a client/ devDependency; it writes the generated client into the web app.
cd "$repo_dir/client"
pnpm exec openapi-ts \
  -i ../openapi/silverloop.json \
  -o ./src/api-client/generated
