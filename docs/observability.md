# Evidence and observability

## Decision evidence

Every simulated decision records a decision evidence ID, wearable evidence ID, source and source
classification, observation timestamp, ingestion and analysis confidence, quality evidence ID,
policy version, selected decision and reasons. `NO_ACTION` is preserved as a first-class result.

Consent changes, coordinator reviews and intervention outcomes are separate append-only records.
Outcome responses show the candidate preference before and after learning; the audit text states
that deterministic safety gates were unchanged. Since ADR
[0005](adr/0005-engagement-and-experience-as-two-learned-signals.md), that preference number is a
product of two Beta posteriors (engagement x experience), so its neutral no-history value is 0.25,
not the 0.5 it was before -- a before/after pair recorded across that change is not comparable on
the same scale.

**Free text the senior typed never reaches the audit trail.** A consent reason is the person's own
words; it stays on its own domain row (`consent_evidence`) and never in the audit trail, which is
an operator surface. The audit event records its length (`reason_length`) instead. (The
follow-through note, day dispute, context-question note and candidate-preference reason were held
to the same rule; their routes, and `GET /v1/simulation/events` that read the trail back, went in
step 7.)

## Structured request logs

FastAPI emits one compact JSON record per request with timestamp, level, request ID, method, the
matched **route template** (`/v1/people/{person_id}/state`, never the concrete path, because a
path segment can carry a person's own words), status and
duration. It does not log bodies, senior notes, wearable values or credentials. A caller
may supply `X-Request-ID`; otherwise the API creates one and returns it in the response header.

## Planner provider failures

The planner loops record a provider exception's **class** in `fallback_reason`, never its text: a
provider message can carry request ids, ARNs, account ids or part of a credential, and the agent
evidence block is append-only and rendered to coordinators. The full text goes to the
`silverloop.agent` logger at WARNING, in the same JSON shape, carrying the request id of the call
that triggered it — so an operator debugging an outage can join the two, and nobody reading the
audit trail sees the provider's words.

## Operational metrics

The web app no longer has an operations or System Health screen, and step 7 removed `GET
/v1/metrics`. `repository.metrics()` stays (`supabase_smoke.py` reads it): evidence, outcome and
open-review counts; consent; last decision; audited no-action count; policy version; source
classifications. `GET /ready` reports the active runtime -- Supabase PostgreSQL, SQLite offline
fallback or not ready -- and the connected and expected schema revisions. See `docs/api.md`. This is intentionally a small demo surface, not a
production monitoring platform.

## Planner fallback visibility

`GET /health`'s `llm_enabled`, read alongside `OperationalMetrics.planner_fallback_modes`, says
plainly whether the outreach planner ran with a model this session or is on a deterministic
fallback -- distinct from `GET /ready`, which only reports whether the database is reachable.

## Counts, never rates

`repository.metrics()` carries numerators and denominators as separate counts; every rate a surface shows
is built from two of them with the denominator printed beside it.

- **Outreach planner:** `planner_runs`, `planner_agent_selected`, `planner_contested_runs`
  (agent-mode runs with at least two permitted candidates -- the only honest denominator for
  agreement, because a planner handed one option can only agree), `planner_agreed_with_ranker` (a
  redundancy measure, not a quality one), fallback modes, guardrail rejections and violations.
- **The user-initiated funnel (no screen):** `activity_searches` -> `activity_results_shown` ->
  `activity_interested` / `activity_not_for_me` (+ `activity_decline_reasons`) ->
  `activities_planned` -> `plans_due` (week entries whose day has passed; the denominator for
  reports) -> `activity_reports` -> `activity_went` -> `activity_enjoyed`.
- **World model quality:** `facts`, `explicit`, `inferred`, `external`, `fixture`, `confirmed`,
  `single_evidence`, `temporary`, `expired_excluded`, `contradictions`, `stale`. Counts only; the
  facts themselves are the senior's and never reach this surface.
- **What the model cost:** `llm_calls`, `llm_latency_ms_total`, `llm_tokens_total`,
  `llm_fallbacks_by_mode`, `guardrail_rejections_by_rule`. Built by
  `sql_repository._llm_cost_observability` from evidence the three LLM entry points already write
  (the outreach planner's `agent` block, the search audit's `agent` and `intent` blocks); nothing
  new is recorded to produce them. Read them together with the notes below.
- **Per search (audit detail, operator surface):** the `ranking` rows — exactly `activity_id`,
  `rank`, `tier`, `total`, `matched_axes`, `coverage`, `variety_promoted`, `series_deferred`,
  `reasons_suppressed` (the number of eligible lines beyond the card face, which the senior sees
  in `RankedActivity.more_reasons` when the card is opened — a count, never a line hidden from
  them) and `factors` (name → weighted contribution); no factor values or notes,
  which only the evaluator-only ranker inspector endpoint (`docs/api.md`) returns — plus event-level
  `ranking_weights`, `planner_agreed_with_ranker` against the pre-planner order,
  `planner_contested`, the planner's `agent` evidence (mode, model, `provider`, `transport`,
  iterations, latency, tool calls), and an `intent` block recording what the free-text parse itself
  cost (mode, model, latency, usage, total tokens). The two planner flags are `null` unless a
  planner actually ran: on the fallback modes — including every offline run — the deterministic
  order was kept by definition, and "the ranker agreed with itself" is not a measurement. They are
  also `null` when `snapshot_stale` is true, because the planner's order was discarded. This matches
  the outreach aggregate above, which counts only `mode == "agent"`. `transport` (`live` |
  `recorded`) is what tells a replayed recording apart from a live model call; `model` alone does
  not.
  The intent parse previously recorded only which parser ran, so its cost had no denominator
  anywhere. Like `ranking` and `agent`, `intent` stays on the stored event and never travels to
  the senior in `ActivityQueryResponse.audit_event`.

### Reading the LLM cost counters

Four things they deliberately do **not** do.

- **They are not rates and never a price.** Counts and sums only, per the section heading above.
  A cost-per-decision figure is a thing an operator computes, with their own provider pricing,
  from numbers whose denominators are printed beside them.
- **`llm_calls` counts runs that reached a model, not opportunities.** A `fallback_disabled` run
  never built a client, so it adds nothing to calls, latency or tokens -- otherwise every
  per-call number would be diluted by runs that never ran. Under `LLM_ENABLED=false` all four
  numeric counters are zero, and that zero is honest rather than absent.
- **`llm_fallbacks_by_mode` includes the `agent` mode.** Every run has exactly one mode and the
  modes sum to the number of runs, so a fallback count cannot be quoted without its denominator.
  Intent-parse modes are prefixed `intent:` because `fallback_error` on the parse and
  `fallback_error` on the ranking loop are different failures with different fixes; the chip path
  (`intent:chips`) is excluded entirely, because no parser ran.
- **`guardrail_rejections_by_rule` classifies recorded prose.** `GuardrailVerdict.violations` are
  sentences written to be read back to the model, not rule ids, so
  `agent.guardrail_rules.classify_violation` maps them to stable names by a table. An
  unrecognised violation is counted under `other` rather than dropped. The activity-order limits
  classify as `over_promotion` (an option moved up more than `MAX_PROMOTION` places) and
  `over_narrowing` (fewer than `MIN_SHOWN_AFTER_NARROWING` kept); they used to fall into `other`. And
  `tests/test_recorded_client.py` asserts that every violation `guardrails.py` can currently emit
  classifies to a named rule -- so rewording one fails a test instead of silently emptying a
  counter. A rule id raised at the point of violation is the better long-term shape.

`llm_latency_ms_total` is wall-clock time this process spent waiting. Under the recorded transport
(`LLM_PROVIDER=recorded`) nothing waits, so it is ~0 and truthfully says so; the latency stored in
a recording is never smuggled into the audit as though this run had taken that long. See
[testing.md](testing.md#the-recorded-llm-transport) for how the recorded transport is tested.

Production deployments should export the same structured fields to their approved logging and
metrics systems, with retention, access control and alert thresholds set by the operator.
