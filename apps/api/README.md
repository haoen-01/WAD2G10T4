# Care+ API

FastAPI owns the decision state machine, policy gates, audit trail and demo state. The implementation
is deterministic and synthetic by default; an LLM is not required.

```bash
uv sync
uv run uvicorn silverloop.main:app --reload
```

Open <http://127.0.0.1:8000/docs>. Use `POST /v1/demo/reset` before a presentation.

For the route-by-route contract (auth, parameters, limits and error responses) see
[`docs/api.md`](../../docs/api.md). For how the modules in `src/silverloop/` fit together -- the
request lifecycle, the decision path, the data model and the runtime profiles -- see
[`docs/architecture.md`](../../docs/architecture.md).
