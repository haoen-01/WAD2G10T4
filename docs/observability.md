# Evidence and observability

## Decision evidence

Every simulated decision records a decision evidence ID, wearable evidence ID, source and source
classification, observation timestamp, ingestion and analysis confidence, quality evidence ID,
policy version, selected decision and reasons. `NO_ACTION` is preserved as a first-class result.

Consent changes, review cases and intervention outcomes are separate append-only records. Outcome
responses show the candidate preference before and after learning; the audit text states that the
deterministic safety gates were unchanged. The preference number is the product of two Beta
posteriors, engagement and experience (ADR
[0005](adr/0005-engagement-and-experience-as-two-learned-signals.md)), so its neutral no-history
value is 0.25.

**Free text the senior typed never reaches the audit trail.** A consent reason is the person's own
words; it stays on its own domain row (`consent_evidence`) and the audit event records only its
length (`reason_length`).

## Structured request logs

FastAPI emits one compact JSON record per request with timestamp, level, request ID, method, the
matched **route template** (`/v1/people/{person_id}/state`, never the concrete path, because a path
segment can carry a person's own words), status and duration. It does not log bodies, notes,
wearable values or credentials. A caller may supply `X-Request-ID`; otherwise the API creates one
and returns it in the response header.

## Planner provider failures

The outreach planner records a provider exception's **class** in `fallback_reason`, never its text:
a provider message can carry request IDs, ARNs, account IDs or part of a credential, and the agent
evidence block is append-only. The full text goes to the `silverloop.agent` logger at WARNING, in
the same JSON shape and with the request ID of the call that triggered it, so the two can be joined
when debugging without the provider's words reaching the audit trail.

## Health, readiness and metrics

- `GET /health` is liveness: `status`, `version`, `mode` and `llm_enabled`, which says whether the
  outreach planner may call a model in this process.
- `GET /ready` reports the database backend, runtime profile, whether the database is connected, the
  connected and expected Alembic revisions, and `tables_without_rls` on PostgreSQL. Any revision
  mismatch or open table makes `status` `not_ready`. See [supabase.md](supabase.md).
- `repository.metrics()` returns `OperationalMetrics`: evidence, intervention, outcome, open-case
  and audited no-action counts, consent, the last decision, policy version, source classifications,
  planner and LLM counters, and world-model quality counts. No route serves it;
  `pnpm demo:supabase-smoke` reads it. This is a small demo surface, not a monitoring platform.

## Counts, never rates

`OperationalMetrics` carries numerators and denominators as separate counts; any rate is built from
two of them with the denominator printed beside it.

- **Outreach planner:** `planner_runs`, `planner_agent_selected`, `planner_contested_runs` (agent
  runs with at least two permitted candidates, the only honest denominator for agreement),
  `planner_agreed_with_ranker` (a redundancy measure, not a quality one), `planner_fallback_modes`,
  guardrail rejections and violations.
- **World-model quality:** `facts`, `explicit`, `inferred`, `external`, `fixture`, `confirmed`,
  `single_evidence`, `temporary`, `expired_excluded`, `contradictions`, `stale`. Counts only.
- **What the model cost:** `llm_calls`, `llm_latency_ms_total`, `llm_tokens_total`,
  `llm_fallbacks_by_mode`, `guardrail_rejections_by_rule`, built by
  `sql_repository._llm_cost_observability` from evidence the planner already writes.
- The activity-search funnel fields (`activity_searches` to `activity_enjoyed`) remain in the model,
  but no route records a search any more.

### Reading the LLM cost counters

- **They are counts and sums, never a price.** Cost per decision is for an operator to compute with
  their own provider pricing.
- **`llm_calls` counts runs that reached a model.** A `fallback_disabled` run adds nothing to calls,
  latency or tokens. Under `LLM_ENABLED=false` all four numeric counters are zero.
- **`llm_fallbacks_by_mode` includes the `agent` mode**, so the modes sum to the number of runs.
- **`guardrail_rejections_by_rule` classifies recorded prose.** Guardrail violations are sentences
  written for the model, so `agent.guardrail_rules.classify_violation` maps them to stable names by
  a table, and an unrecognised one is counted under `other`. `tests/test_recorded_client.py`
  asserts that every violation `guardrails.py` can emit classifies to a named rule.

`llm_latency_ms_total` is wall-clock time this process spent waiting. Under the recorded transport
(`LLM_PROVIDER=recorded`) nothing waits, so it is close to zero; the latency stored in a recording
is never reported as this run's.

Production deployments should export the same structured fields to their approved logging and
metrics systems, with retention, access control and alert thresholds set by the operator.
