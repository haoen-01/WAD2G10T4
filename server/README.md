# Care+ API

FastAPI owns the decision loop, the policy gates, the audit trail, the family data and the demo
state. The Python package is `silverloop` (`src/silverloop/`). It is deterministic and synthetic by
default; no LLM is required.

From the repository root, `pnpm dev:api` runs the runtime check, `alembic upgrade head` and
uvicorn on <http://127.0.0.1:8000>; `pnpm demo:offline` runs it on SQLite with the offline
profile. Settings are read from the root `.env` (and `server/.env`). Directly, from `server/`:

```bash
uv sync
uv run uvicorn silverloop.main:app --reload
```

On start the API migrates the database, applies the RLS posture on PostgreSQL and seeds a scenario
if none is active. Open <http://127.0.0.1:8000/docs>; `POST /v1/demo/reset` starts the demo over.

On Vercel the project root is `server/` and `index.py` serves `app` (`[tool.vercel]` in
`pyproject.toml`).

For the route-by-route contract see [`docs/api.md`](../docs/api.md); for how the modules fit
together see [`docs/architecture.md`](../docs/architecture.md).
