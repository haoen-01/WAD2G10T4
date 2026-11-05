# Architecture overview

Care+ is a web app that helps a family look after an older relative living on their own. A
simulated smartwatch tracks the senior's daily activity; the API learns their usual day, checks
the data is good enough to read, and a deterministic policy picks the least intrusive permitted
action. Around that loop sit the family features: care groups, a shared calendar, tasks, an
activity feed, check-ins, badges, a walk-sharing map and Kaki, a read-only assistant. Care+ is not
a medical or emergency system; see [the principles](principles.md).

## Boundary

```text
Vue SPA -> Axios (careApi.ts) -> FastAPI -> repository interface
                                           |            |
                                           |            +-> PostgreSQL/Supabase (shared default)
                                           |            +-> SQLite (tests/offline fallback)
                                           |
                                           +-> analytics -> deterministic policy -> bounded action
                                                                  |                 |
                                                                  +-> audit evidence +-> outcome
                                                                                         |
                                                                                  preference ranker
```

FastAPI owns domain validation, state transitions, action permission and audit evidence. The
browser never changes domain state directly. SQLAlchemy repositories persist every simulated day;
a demo reset starts a new run without deleting earlier decision, consent, review, outcome or audit
evidence.

## Decision summary

- `client/`, `e2e/` and `server/` are separate installs (pnpm for the first two, uv for the API);
  the root `package.json` has no dependencies and only runs scripts that delegate to them.
- The Vue web app (a Vite single-page app styled with Bootstrap 5, in `client`) provides the
  Home, Senior, Walk, Calendar, Family and Watch screens, plus sign-in, sign-up and the group
  start page (`client/src/router/index.ts`). It has no server side: sign-in uses
  `@supabase/supabase-js`, and every domain read and write is an Axios call in
  `services/careApi.ts`, typed with the generated client's types. Home's weather card and the
  calendar's public holidays call data.gov.sg and Nager.Date directly (`services/publicApis.ts`).
  Tasks are shown on Home, Senior and the Calendar (`composables/useTasks.ts`, rules in
  `lib/tasks.ts`; see [tasks](tasks.md)).
- The family screens are an app-style shell: a bottom tab bar on phones and a header pill on
  desktop (`components/ui/MainNav.vue`, CSS only). Home shows the family activity feed and
  check-ins (`composables/useFamilyActivity.ts`: one polling store per app, 30 s and on focus,
  paused while hidden); the Calendar's phone bottom sheet carries each day's family notes
  (`composables/useAppointmentNotes.ts`, one per open sheet). The browser writes the feed's
  sentences from structured entries (`lib/family-feed.ts`); state changes are pure functions in
  `lib/*` with `node --test` coverage.
- The Walk page's shared walk and the "Still for a while" check-in run on a simulated walk in the
  browser (`composables/useWalk.ts`, `lib/demo-walk.ts`, map by `maplibre-gl`). There is no
  location API: nothing about the walk is sent to the server. Badges are worked out in the browser
  from the daily metrics and shared walks (`lib/badges.ts`, see [badges](badges.md)) and never
  feed a decision.
- Motion uses `motion-v` (with `@vueuse/core`), pinned exactly, in `components/motion/*`. It is
  imported only from lazily loaded views, so its chunk never loads with the senior or sign-in
  screens, and every motion component falls back to instant or opacity-only under
  `prefers-reduced-motion`. Drags always have a button that does the same. The bottom sheet and
  the toast host are teleported to `<body>`; while the sheet is open `#app` is `inert`, and toasts
  stay outside it so they are announced and reachable.
- FastAPI/Pydantic is the API source of truth; CI regenerates and verifies the TypeScript client.
- SQLAlchemy 2 + Alembic own the PostgreSQL/SQLite schema. Supabase is the shared runtime, denies
  browser roles and accepts domain writes only through FastAPI. SQLite is for tests and the
  offline demo.
- Internal tools are typed Python functions; MCP is not used for in-process calls.
- LLM use is optional and bounded. The policy never depends on it.

## Learning boundary

The Beta-Bernoulli learner ranks message or programme candidates only after the deterministic
policy has permitted that action class. Outcomes can change a candidate's rank, but never the
consent, data-quality, confidence, contact-cap, stale-programme or review gates.

`learning.PreferenceLearner` keeps two Beta-Bernoulli posteriors per candidate
([ADR 0005](adr/0005-engagement-and-experience-as-two-learned-signals.md)):

- **Engagement** (would this person accept and follow through on this option again) is folded
  from the outcome weight, replaced by the follow-through weight once one arrives. It is
  reason-keyed: a `bad_day` or `already_active` decline carries zero weight, every other reason
  carries the bare decline's, and `unable` is half a unit. `deferred` moves nothing and
  `no_response` counts at half weight.
- **Experience** (given they attended, was it any good) is folded from the enjoyment weight
  (`enjoyed` / `okay` / `not_for_me`), only when the follow-through says they attended
  (`completed` or `partial`). With no report it reads the neutral Beta(1, 1) prior (0.5).

The single number other modules read (`expected_value`) is their product,
`P(attend) x E[enjoy | attend]`, so an option nobody attends cannot outrank one people attend and
enjoy. Administrative closure (`coordinator_resolved`) never reaches the learner: `record_outcome`
rejects it. Muting after `DECLINES_BEFORE_SUPPRESSION` (3) declines is deterministic and
reason-aware in the same way.

No route records follow-through or enjoyment any more, so in the running app engagement comes
from the senior's tap on the suggestion card (accepted, declined with an optional reason,
deferred) and from the response clock (see below); experience stays at the prior.

The dimensional learner (`preferences.py`) ranks _kinds_ of activity and keeps three source tiers
(`senior_statement` > `decline_reason` > `inferred`) as separate rows; a stated preference on a
dimension supersedes inferred rows rather than being averaged with them. Rows carry a nullable
`run_id` ([ADR 0004](adr/0004-run-scope-activity-dimension-preferences.md)): a standing
statement has `run_id = null` and survives a reset, like `candidate_preferences` (outreach mutes);
every other row is stamped with its run, so a reset makes it read as absent rather than deleting
it. While consent is withdrawn nothing new is inferred.

## Module map

`server/src/silverloop/` is about 40,000 lines; `sql_repository.py` is the largest file at about
9,000. This is what each file owns; [the API reference](api.md) covers the HTTP surface.

**What the screens use.** The web app calls the routes in `client/src/services/careApi.ts`
(person state and metrics, interventions and their outcomes, `/v1/me`, care groups, the family
calendar, the activity feed and check-ins, asks and notifications, per-day appointment notes,
tasks, the watch status, the family agents, "Read my day" and the assistant) plus `/v1/auth/me`.
The e2e suite and demo tooling also call `/v1/demo/reset`, `/v1/simulation/advance` and
`/v1/people/{id}/consent`. Routes for coordinator review, the review setting, week plans,
preferences, goals, activity search and the evaluator no longer exist. The modules `advance`
still runs stay (the review setting feeds `policy.decide`; review cases and replan offers are
written there), so they are kept and tested.

Top-level modules:

- `main.py` -- `create_app()` (the FastAPI app factory), CORS and structured request-logging
  middleware, the system, demo, person, intervention and simulation routes, and the app-level
  mapping from repository exceptions to HTTP status codes. It registers the family and assistant
  routes from their own modules. See [Request lifecycle](#request-lifecycle).
- `models.py` -- the Pydantic contract: every request/response shape and enum (`Decision`,
  `PolicyGate`, `OutcomeKind`, `TraceStatus`, ...). Editing it changes `openapi/silverloop.json`
  and the generated TypeScript client.
- `repository.py` -- the `SilverLoopRepository` `Protocol`: the persistence boundary `main.py`
  depends on. `main.py` does not import SQLAlchemy or `sql_repository.py` directly.
- `sql_repository.py` -- the single implementation of that Protocol: session management, every
  domain read/write of the daily loop, the decision-trace builder, learner wiring, and the call
  sites into the outreach planner.
- `family_groups.py` / `family_calendar.py` / `family_activity.py` / `family_asks.py` /
  `family_tasks.py` / `family_routes.py` -- care groups (sign-up as senior or family, the
  senior-link and join PINs, approval), the shared calendar (appointments, availability, helpers,
  per-day notes), the activity feed and check-ins, asks and in-app notifications, tasks, and the
  `/v1/me`, `/v1/groups/...` and family-facing `/v1/people/...` routes. Their stores share the
  repository's database sessions. `family_activity.py` and `family_asks.py` import
  nothing from the decision path (tested), and nothing in `advance` reads tasks.
- `family_catchup.py` / `family_drafts.py` / `senior_day.py` -- assemble the context for the
  catch-up card, the typed appointment draft and "Read my day" through the stores'
  permission-checked reads; the agents in `agent/` only see that context.
- `assistant.py` / `assistant_routes.py` -- Kaki, the read-only assistant
  (`POST /v1/assistant/chat`). Emergency, medicine and symptom questions get a fixed safety reply
  and never reach a model; OpenAI answers only when `OPENAI_API_KEY` is set and the profile is not
  `offline`, otherwise a built-in helper answers. See [ADR 0013](adr/0013-care-plus-assistant.md)
  and [the assistant](assistant.md).
- `wearable_status.py` -- the simulated watch status (connected, last sync, battery). No real
  device is connected.
- `db_models.py` -- the SQLAlchemy 2 declarative schema. See [Data model](#data-model).
- `policy.py` -- the deterministic decision ladder (`decide`); the one place safety gates live.
  See [The decision path in detail](#the-decision-path-in-detail).
- `quality.py` -- the 8-hour minimum wear-time gate (`assess_data_quality`).
- `analytics.py` -- the median/MAD rolling baseline, the anchored reference, the baseline-drift
  floor, sustained-low-day counting and confidence scoring (`analyse_signal`).
- `baseline_confirmation.py` -- the "is this your new normal?" question that is the only way to
  re-anchor the reference.
- `review_threshold.py` / `review_threshold_replay.py` -- the per-person review setting, its
  bounds, the absolute floor and the shadow check
  ([ADR 0008](adr/0008-coordinator-calibrated-review-threshold.md),
  [the spec](review-threshold-spec.md)).
- `learning.py` -- the per-candidate learner described above. Ranks only; never gates.
- `preferences.py` -- the dimensional preference learner.
- `consent_scopes.py` -- names what the single stored consent flag covers in each place it is
  read.
- `context.py` -- optional live weather and public-holiday context (data.gov.sg, `date.nager.at`).
  Any failure degrades to a confidence-0 "unavailable" evidence item; force-disabled under the
  `offline` profile.
- `context_question.py` / `context_explanation.py` -- whether the one quiet-day question is worth
  asking, and what a recorded answer means for the ladder. Neither re-runs the ladder.
- `ontology.py` -- activity types, families and formats, with one alias table (English, Singlish,
  Chinese) shared by catalogue normalisation and the tests.
- `activity_search.py` / `replanning.py` -- the deterministic filter and ranker over the activity
  catalogue, and replan detection for a planned activity that became full, cancelled or rained
  out. `advance` still calls them; see [Replanning](#the-activity-catalogue-and-replanning).
- `world_model.py` / `follow_up.py` -- a read model of what Care+ knows about one person, and a
  description (never a causal claim) of what activity did after a piece of outreach. Both back
  `repository.metrics()`, which `supabase_smoke.py` reads.
- `fixtures.py` -- synthetic persona histories, the activity catalogue fixture and demo-reset
  content.
- `runtime.py` -- `validate_runtime`: refuses to start on a misconfigured profile. See
  [Runtime profiles](#runtime-profiles).
- `config.py` -- `Settings` (pydantic-settings): every environment-driven flag.
- `auth.py` -- Supabase JWT verification (JWKS fetch/cache, ES256/RS256/HS256) and the FastAPI
  dependencies the routes use (`Senior`, `PersonReader`, `Family`, `SignedIn`, `DemoOperator`,
  `AnyUser`; `Coordinator` exists but no route uses it).
- `stored_state.py` / `error_responses.py` -- stored simulation snapshots from an older contract
  raise `StoredStateIncompatible`; app-level handlers return classified 500 bodies.
- `local_time.py` -- the one place "morning"/"afternoon" is computed from a person's local wall
  clock (everything is stored in UTC).
- `logging_config.py` -- the structured JSON log formatter.
- `migrations.py` / `schema_revision.py` -- run `alembic upgrade head` and re-apply the RLS
  posture at startup, and read the Alembic head revision for `/ready`.
- `openapi.py` -- `python -m silverloop.openapi`, writes `openapi/silverloop.json`; wired to
  `pnpm client:generate`.
- `scenarios.py` -- replays YAML scenario files for `pnpm test:scenarios`.
- `seed.py` / `smoke.py` / `supabase_smoke.py` / `demo_story.py` -- seed every persona; an HTTP
  smoke test; the Supabase equivalent; and `pnpm demo:story`, which puts the signed-in demo into
  its starting state.
- `setup_demo_accounts.py` -- provisions demo Supabase accounts; refuses to run under
  `APP_ENV=production` without `--allow-production`. See [Supabase](supabase.md).

Subpackages:

- `adapters/` -- the provider-neutral ingestion boundary (`AdapterBatch`, `CanonicalDailyMetric`,
  `SourceClassification`). `synthetic.py` is the default deterministic history; `csv_sample.py`
  reads a pre-aggregated CSV; `apple_export.py` parses an Apple Health `export.xml` file. None is
  a live integration. See [data adapters](data-adapters.md).
- `agent/` -- the bounded LLM loops, all off by default (`LLM_ENABLED=false`). `planner.py` holds
  `plan_outreach` (which permitted candidate to offer and how to word it);
  `guardrails.py` is the deterministic boundary that rejects clinical, pressuring or untrue copy
  and any candidate outside the permitted set; `tools.py` is the read-only tool surface;
  `constants.py` fixes model ids and limits; `models.py` defines the audit records. `loop.py` is
  the shared loop for the read-only family agents (`catchup.py`, `my_day.py`,
  `appointment_draft.py`): the model calls read-only tools, then a submit tool that a
  deterministic check approves or sends back. Nothing is written; the draft only fills the form.
  With the flag off, offline, past the per-person limit, on a provider error, past the deadline or
  after a rejection, the same answer is assembled deterministically and the response says which
  (`mode`, `source`, `steps`). See [the agentic layer](agentic-layer.md),
  [agentic features](agentic-features.md) and
  [ADR 0015](adr/0015-read-only-family-agents.md).
- `tts/` -- the opt-in "Read my day" voice: Kokoro-82M on the API's own CPU, from the `tts`
  dependency group (`uv sync --group tts`). Without it the speech route answers 503 and the
  browser reads with its own on-device voices. See [Read my day voice](read-my-day-voice.md).

On the client, Pinia stores (`client/src/stores/`: `session`, `activity`, `calendar`) own the
state several screens share (who is signed in and which senior is shown, the senior's activity,
the family calendar). They hold only what the API returned, and `stores/reset.ts`
`clearViewerStores()` clears them on sign-out and when the session expires.

## Request lifecycle

The Vue app calls a route in `main.py`, `family_routes.py` or `assistant_routes.py` with Axios,
through `client/src/services/careApi.ts`, typed with the generated client's types
(`client/src/api-client`). The route depends on one of the `auth.py` dependencies, which verifies
the bearer JWT and injects a typed `CurrentUser`, or, with `AUTH_ENABLED=false`, substitutes a
fixed synthetic identity and skips verification. Person-scoped routes then check scope:
`check_reader` lets a senior read only themselves and a family member only the senior of a group
they are an active member of, and answers 404 (not 403) otherwise. See "Auth, in brief" in
[the API reference](api.md).

The route then calls the injected repository
(`Annotated[SilverLoopRepository, Depends(get_repository)]`), at runtime the one
`SqlAlchemyRepository` held on `app.state.repository`. Inside it, every mutating call opens one
`session.begin()` transaction; domain rules surface as `KeyError` (not found), `ValueError` (a
business-rule conflict), `RuntimeError` (a person with no active, seeded run), `StaleRunConflict`
or, on a racing write, `IntegrityError`. Most routes map these locally; `main.py` also registers
app-level fallback handlers (`register_exception_handlers`). See "Fallback error handling" in
[the API reference](api.md).

The response is a Pydantic model from `models.py`. `pnpm client:generate` writes
`openapi/silverloop.json` and regenerates `client/src/api-client/generated`; `pnpm client:check`
fails CI if either would differ from what the code produces.

## The decision path in detail

`POST /v1/simulation/advance` walks the full path below (the demo and scenario event mechanism; see
[the API reference](api.md) for the allowed events). `SqlAlchemyRepository.advance` synthesises
the next day's `DailyMetric` for the chosen event and, for the weather events, a `ContextSignal`.

1. **Baseline.** `analytics.analyse_signal` calls `quality.assess_data_quality` first (the 8-hour
   wear-time gate) and only computes a baseline if the day is interpretable:
   `analytics.calculate_baseline` (28-day rolling median/MAD, an anchored reference from the
   earliest valid days on record, and a floor at `BASELINE_DRIFT_FLOOR = 0.85` of that reference,
   so a baseline that has followed a sustained decline down is not read as normal) and a
   `SignalSummary` (`delta_percent`, `robust_z`, `sustained_low_days`, `confidence`). Once the
   floor has bound for `CANDIDATE_BASELINE_STREAK_DAYS` (28) days, the state carries
   `pending_baseline_confirmation`: only the person can confirm a new normal
   (`baseline_confirmation.py`). No route records that answer today.
2. **Policy gate.** `policy.decide` runs the ladder as a fixed sequence of early returns:
   **consent** (inactive -> `SUPPRESS`) -> **data quality** (`safe_to_interpret`, else
   `NO_ACTION`) -> **confidence** (`>= 0.45`) -> **stated explanation** (the person's own answer
   to the quiet-day question, only below the review rung's persistence) -> **rain context**
   (`context.rainy` and fewer than 2 sustained low days) -> **small baseline** (a positive
   baseline under 500 steps) -> **severity/persistence**: the person's review setting (starting at
   40% for 3 days), the absolute floor (60% for 3 days) and the shadow check all give
   `COORDINATOR_REVIEW`; `>= 2` days and `>= 25%` gives `PROGRAMME_SUGGESTION`; `>= 20%` gives
   `GENTLE_NUDGE`; otherwise `NO_ACTION`. The **contact guard** (a cap of 2 contacts in the last
   seven simulated days, or a 3-day cooldown after an accepted suggestion; either gives
   `SUPPRESS`) applies only inside the programme and nudge branches, never to a review. Both
   guards count the person's simulated days, so advancing a simulated week releases the budget
   exactly as living through one would. `PolicyResult.decided_by` names the gate (`PolicyGate`).
3. **Action.** `GENTLE_NUDGE`/`PROGRAMME_SUGGESTION` create one `Intervention`;
   `COORDINATOR_REVIEW` opens or refreshes a single `ReviewCase` per person (no screen shows it
   yet); `SUPPRESS`/`NO_ACTION` write no outreach, only the audit trail.
4. **Candidate selection.** The per-candidate learner ranks the permitted candidates, and the
   top-ranked candidate and its message are held as the fallback _before_ anything else runs
   (`_prepare_outreach_plan`). `agent.planner.plan_outreach` may then choose among that same set
   and reword the message (`_plan_outreach_safely`, with no database session open); on any failure
   (disabled, unavailable, an API error, an exhausted iteration budget or no proposal) the
   deterministic fallback is used verbatim, so `LLM_ENABLED=false` and a provider outage take the
   same code path.
5. **The response clock.** Before the day is decided, `advance()` closes any offer still
   `proposed` with no outcome `RESPONSE_WINDOW_DAYS` (2) simulated days after it was made: one
   append-only `no_response` outcome row with actor `system` and an
   `intervention_outcome_recorded` audit event (`resolved_by: response_window`). It is not a
   decline and does not count towards a mute. The intervention row is locked
   (`SELECT ... FOR UPDATE` on PostgreSQL) both here and in `record_outcome`, so a person's answer
   always wins a race with the clock.
6. **Outcome and learning.** The senior's answer feeds the per-candidate learner and the
   dimensional learner, never `policy.py`. Neither learner can create, escalate, downgrade or
   suppress a decision; they only reorder what the ladder already permitted.

## The decision trace

`_build_loop_trace` in `sql_repository.py` builds one `list[DecisionTraceStep]` per `advance()`
call: ten stages, in fixed order -- `observation`, `validation`, `reasoning`, `policy_gate`,
`action`, `response`, `outcome`, `follow_through`, `learning`, `audit`. Each step carries a
`TraceStatus` (`completed` / `blocked` / `pending` / `not_applicable`), a `title`/`detail`, and an
`evidence_id` pointing at the evidence row it describes.

No screen shows the trace, so it is asserted against the API response directly. It is returned on
`AdvanceResponse.loop_trace` and stored as JSON on `simulation_events.response_json`, so an
idempotent `POST /v1/simulation/advance` replay returns the stored trace without recomputing it.

## Data model

Every table lives in `db_models.py`, owned by SQLAlchemy 2 and Alembic.
Grouped by area, with whether each is append-only, write-once, or updated in place:

- **Identity and run state.** `people`; `scenario_runs` (one active run per person;
  `current_day`/`active` updated in place); `auth_user_person_links` (maps a Supabase `sub` to one
  `person_id`).
- **Sensor evidence.** `daily_metrics` (append-only); `simulation_events` (append-only, one row
  per distinct `event_id`, replayed rather than reprocessed); `day_disputes` (append-only).
- **Decisions and audit.** `decision_evidence`, `audit_events` and `consent_evidence` (all
  append-only; a withdrawal is a new row).
- **Outreach and its follow-through.** `interventions` (`status` updated as the loop progresses);
  `intervention_outcomes` (append-only, enforced by a database trigger: a decline reason added
  later is a second, newer row, and every reader resolves to the latest row per intervention);
  `intervention_follow_through` and `intervention_enjoyment` (write-once per intervention; no
  route writes them now).
- **Review.** `review_cases` (refreshed in place while open); `case_reviews` (append-only);
  `review_threshold_proposals` and `review_threshold_decisions` (the review setting).
- **Programmes and the activity catalogue.** `programmes` (the outreach fixture) and
  `activity_candidates` (the wider activity catalogue).
- **Preferences and memory.** `candidate_preferences` (mutes, unique per
  `(person_id, candidate_key)`); `activity_dimension_preferences` (unique per
  `(person_id, dimension, value, source)`); `activity_offer_responses`, `plan_follow_through` and
  `plan_enjoyment` (append-only); `proposed_memories`; `context_question_answers` (write-once per
  `(run_id, question_id)`); `baseline_confirmations` (append-only; the latest `confirm` is the
  reference).
- **Goals and the week.** `activity_goals`, `week_plan_entries` and `replan_offers`. No route
  writes goals or plans, so in the running app these stay empty.
- **Accounts and family.** `accounts` (one per signed-up user, `senior` or `family`);
  `care_groups` (at most one per senior; `person_id` is null until the senior is linked) and
  `group_members` (`pending` until approved); `family_pins` (hashed PINs with expiry) and
  `pin_attempts` (wrong-PIN lockout); `appointments`, `availability_entries` and
  `helper_assignments` (the shared calendar); `appointment_notes` (per-day, group-only, deleted
  with their appointment); `tasks` and `task_ticks`; `family_activity` (the feed: append-only,
  cleared only by the demo reset); `helper_asks` (at most one open per appointment day) and
  `notifications` (only `read_at` changes).

## Schema ownership

SQLAlchemy 2 (`db_models.py`) and Alembic (`server/alembic/versions/`, 27 revisions) are the
schema of record for both PostgreSQL/Supabase and SQLite; `migrations.py` runs
`alembic upgrade head` at API startup. `infra/supabase/migrations` is a **hand-maintained SQL
mirror** of that schema for the Supabase project (28 files: Alembic's DDL plus the `REVOKE`-based
deny policies for the `anon` and `authenticated` Data API roles, which are Supabase concerns and do
not belong in the Alembic chain).

Because the mirror is hand-written, it can drift. One known difference: the mirror adds an
append-only trigger (`reject_silverloop_evidence_mutation`) to `intervention_follow_through` and
`day_disputes`, but the Alembic revision it mirrors (`d4a7c1f9e2b3_add_follow_through_loop.py`)
does not, so those two tables are append-only only on a database built from the mirror.
`server/tests/test_supabase_mirror.py` checks that every ORM table gets RLS and a deny policy in
the mirror; nothing checks the rest of its DDL. `GET /ready` compares the live `alembic_version`
with the repository's head, which catches revision drift but not content drift. See
[Supabase](supabase.md).

## Runtime profiles

`Settings.silverloop_runtime_profile` (env `CAREPLUS_RUNTIME_PROFILE`, or the older
`SILVERLOOP_RUNTIME_PROFILE` when that is unset; default `shared`) is validated once, at startup,
by `runtime.validate_runtime`:

- **`shared`** requires a PostgreSQL `DATABASE_URL` and refuses one still containing a placeholder
  (`PROJECT_REF`, `REGION`, `:password@`, `<password>`).
- **`offline`** requires SQLite, `ADAPTER_MODE=fixture` and `LLM_ENABLED=false` (or
  `LLM_PROVIDER=recorded`, which replays a committed recording and makes no network call).
  `pnpm demo:offline` is the one sanctioned non-Postgres run and works with no network at all.
- **`EXTERNAL_CONTEXT_ENABLED`** (live weather and holidays in `context.py`) defaults `false`, and
  `create_app` force-disables it under `offline`.
- **`LLM_ENABLED`** defaults `false`. When it is `true` with a working provider, the outreach
  planner and the family agents genuinely call the model, always behind their deterministic
  checks. The demo, the tests and the `offline` profile run with it off (or replayed), so the path
  exercised end to end is the deterministic one. `validate_runtime` refuses to start with
  `LLM_ENABLED=true` and no usable credential for the chosen provider (an Anthropic key, Bedrock's
  AWS credential chain plus a region, an OpenAI key, or a recording path), so an operator learns
  at startup rather than mid-demo that the planner would fall back.
- `AUTH_ENABLED=false` is refused outright when `APP_ENV=production`.

## The activity catalogue and replanning

The activity-search and planning code has no route any more; what `advance` still runs of it
stays. It answers a different question from the policy ladder: `policy.decide` asks "should we
contact this person?", while this code asks "what should we suggest?". None of
`activity_search.py`, `preferences.py`, `replanning.py` or `context_question.py` imports
`policy.py`.

**Ranking** (`activity_search.py`, pure): a hard filter first (only where a mismatch is a barrier
the person cannot cross -- a stated distance, a day, a time window, an environment, company,
capacity, language -- or something they explicitly excluded), then six bounded factors
(`RANKING_WEIGHTS`: intent, preference, engagement, repetition, context, friction), a series
dedupe, one diversity swap, and the top K. Unknown fields are never a penalty: comparisons are
three-valued (`Tri = MATCH | MISMATCH | UNKNOWN`) and UNKNOWN is left out of every fit.
`preferences.resolve` is the only thing the ranker reads about a person.

**Replanning.** `advance()` applies a world change (a listing filling up, the forecast turning)
and, in the same transaction, runs `replanning.notices_for` over the active run's upcoming plans,
writing one `ReplanOfferRow` per notice plus a `replan_offered` audit row. `reason` is a closed
code (`full`, `cancelled`, `weather`). `weather_turns` changes no listing; it only sets the rain
context. `programme_becomes_full` marks only a listing the person has planned. Any alternative
comes from the same deterministic filter and ranker (`alternative_rank_basis: "deterministic"`).
No route writes a plan or answers an offer, so in the running app no offers are written.
