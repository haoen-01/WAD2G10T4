# Architecture overview

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
browser never mutates domain state directly. SQLAlchemy repositories persist every scenario step;
demo reset starts a new run without deleting prior decision, consent, review, outcome or audit
evidence.

## Decision summary

- pnpm + thin Nx coordinate tasks; uv manages Python.
- The Vue web app (a Vite single-page app styled with Bootstrap 5, in `apps/web`) provides the
  Home, Senior, Calendar and Family screens. It has no server side: sign-in uses
  `@supabase/supabase-js`, and every domain read and write is an Axios call in
  `services/careApi.ts`, typed with the generated client's types. Home's weather card and the
  calendar's public holidays call data.gov.sg and Nager.Date directly (`services/publicApis.ts`).
  Calendar and Family screens use the family API. The exception is tasks (Home, Senior, and shown
  on the Calendar): the API has no such concept yet, so they are kept in the browser's
  `localStorage` (`composables/useTasks.ts`, rules in `lib/tasks.ts`; see `docs/tasks.md`).
- FastAPI/Pydantic is the API source of truth; CI regenerates and verifies the TypeScript SDK.
- SQLAlchemy 2 + Alembic own the PostgreSQL/SQLite schema. Supabase is the shared runtime, denies
  browser roles and accepts domain writes only through FastAPI. SQLite is explicit test and
  emergency-demo infrastructure.
- Internal tools are typed Python functions; MCP is not required for in-process calls.
- LLM use is optional and bounded. Policies never depend on it.

## Learning boundary

The transparent Beta-Bernoulli learner ranks message or programme candidates only after the
deterministic policy has permitted that action class. Outcomes can change a candidate's rank, but
never consent, data-quality, confidence, contact-cap, stale-programme or human-review gates.

`learning.PreferenceLearner` keeps two Beta-Bernoulli posteriors per candidate, not one
(ADR [0005](adr/0005-engagement-and-experience-as-two-learned-signals.md)). ENGAGEMENT --
would this person accept and follow through on this option again -- is folded from the outcome
weight, superseded by the follow-through weight once it arrives, exactly as before. EXPERIENCE --
given they attended, was it any good -- is folded from the enjoyment weight (`enjoyed` / `okay` /
`not_for_me`), and only when the follow-through says they actually attended (`completed` or
`partial`); an enjoyment report attached to `not_this_time`/`unable` is a fact about attendance
recorded under the wrong prompt, not evidence about the experience, and moves nothing. The single
number every other module reads (`expected_value`) is their product, an honest
`P(attend) x E[enjoy | attend]`: an option nobody attends cannot out-rank one people attend and
enjoy just because its few reports are glowing, and an option people reliably attend is not erased
by a lukewarm "okay" the way the single collapsed posterior used to erase it. A candidate with no
enjoyment report at all reads EXPERIENCE at the neutral Beta(1, 1) prior (0.5) -- missing, not
negative -- so an unreported experience never drags a well-attended candidate below what its
engagement alone would earn it. ENGAGEMENT is also reason-keyed: the one-tap `DeclineReason`
stored on the outcome row reaches the learner, and `bad_day` ("a fact about the day") and
`already_active` ("the tracker is wrong") carry zero weight while every other reason carries the
bare decline's; `unable` is half a unit, not a full one, because "I couldn't today" is not "I
won't". Administrative closure (`coordinator_resolved`) has no weight at all -- it cannot reach
the learner, because `record_outcome` rejects it and case review writes no outcome row. Suppression
after `DECLINES_BEFORE_SUPPRESSION` declines is deterministic and reason-aware in the same way: a
`bad_day` or `already_active` decline says nothing about the option and never counts toward muting
it.

The dimensional learner (`preferences.py`) ranks _kinds_ of activity for the user-initiated loop
and keeps three source tiers -- `senior_statement` > `decline_reason` > `inferred` -- as separate
rows. Where the person has stated a preference on a dimension, that statement is the whole
contribution and the inferred rows on that dimension are superseded, not averaged in. Learned rows
may carry an `expires_at` decided on the person's simulated calendar.
`activity_dimension_preferences` already carries a nullable `run_id` (ADR
[0004](adr/0004-run-scope-activity-dimension-preferences.md), migration `c2725d7de5df`): a
standing `senior_statement` row (no `until`) has `run_id = null` and survives a reset as a
standing instruction, exactly like `candidate_preferences` (outreach mutes); every other row -- a
time-boxed statement or a `decline_reason`/`inferred` row -- is stamped with the run that produced
it, so a demo reset makes it read as absent rather than deleting anything. See `docs/api.md`'s
closed-loop section for the exact rule each kind of row follows. While consent is withdrawn
nothing new is inferred: the answer is recorded, the stated preference is honoured, the
`decline_reason` / `inferred` tiers are not written.

**Outcome taxonomy.** Offered -> `accepted` / `declined` (+ reason) / `deferred` / `no_response`
(outreach) or `interested` / `not_for_me` (+ reason) (search) -> attended (`completed`, `partial`,
`went`) / missed (`not_this_time`, `did_not_go`) / `cancelled` / `unable` -> `enjoyed` / `okay` /
`not_for_me`. `activity_recovered` is the one outcome tied to the product's actual goal and is
scored as such; it is not attributable to the offer and is never reported as if it were.

## Module map

`apps/api/src/silverloop/` is about 45,000 lines, a third of it `sql_repository.py`. This is what
each file owns; `docs/api.md` covers the HTTP surface these files back.

**What the screens use.** The web app calls about 25 of the API's 80 routes: person state and
metrics, interventions and their outcomes, `/v1/me`, care groups, the family calendar and the watch
status (all listed in `apps/web/src/services/careApi.ts`). The e2e suite also calls
`/v1/demo/reset` and `/v1/simulation/advance`. The rest serve features with no current screen:
coordinator review (queue, cases, review setting, care priorities), the evaluator ranker inspector,
activity search, week plans, goals, preferences, the world model and replanning. Several of those
still run inside `advance` every simulated day (the review setting feeds `policy.decide`; review
cases and replan offers are written there), so they are kept and tested.

Top-level modules:

- `main.py` -- `create_app()` (the FastAPI app factory), CORS and structured
  request-logging middleware, every HTTP route, and both the route-local and app-level fallback
  mapping from repository exceptions (`KeyError`/`ValueError`/`RuntimeError`/`IntegrityError`) to
  HTTP status codes. See [Request lifecycle](#request-lifecycle).
- `models.py` -- the Pydantic contract: every request/response shape and enum
  (`Decision`, `OutcomeKind`, `FollowThrough`, `TraceStatus`, ...). This is the public API surface;
  editing it changes `openapi/silverloop.json` and the generated TypeScript SDK.
- `repository.py` -- the `SilverLoopRepository` `Protocol`: the persistence boundary
  `main.py` depends on. Nothing in `main.py` imports SQLAlchemy or `sql_repository.py` directly.
- `sql_repository.py` -- the single implementation of that Protocol: SQLAlchemy 2
  session management, every domain read/write, the decision-trace builder, learner wiring, and the
  call sites into the outreach/activity planning agent. By far the largest module in the API.
- `family_groups.py` / `family_calendar.py` / `family_activity.py` / `family_routes.py` -- care
  groups (sign-up as senior or family, the senior-link and join PINs, approval), the shared calendar
  (appointments, family availability, who is helping, per-day appointment notes), the family activity feed and check-ins, and
  the `/v1/me` and `/v1/groups/...` routes for all of them. They own their own tables and share the
  repository's database sessions. `family_activity.py` imports nothing from the decision path
  (tested).
- `wearable_status.py` -- the simulated watch status on Home (connected, last sync, battery). No
  real device is connected.
- `db_models.py` -- the SQLAlchemy 2 declarative schema. See [Data model](#data-model).
- `policy.py` -- the deterministic decision ladder (`decide`); the one place safety
  gates live. See [The decision path in detail](#the-decision-path-in-detail).
- `quality.py` -- the 8-hour minimum wear-time gate (`assess_data_quality`); decides
  whether one day's reading is safe to interpret at all.
- `analytics.py` -- the median/MAD rolling baseline, the anchored reference, the
  baseline-drift floor, sustained-low-day persistence counting, and confidence scoring
  (`analyse_signal`).
- `learning.py` -- the transparent, weighted Beta-Bernoulli preference learner over
  per-candidate outcomes: an ENGAGEMENT posterior and an EXPERIENCE posterior, combined into one
  ranking signal (ADR 0005). Ranks only; never gates.
- `preferences.py` -- the dimensional preference learner: a decline reason moves the
  score of a _kind_ of activity (distance, intensity, timing, social shape, environment), not just
  the one listing declined, and never touches the per-candidate learner's state.
- `context.py` -- optional live weather and public-holiday context (data.gov.sg
  rainfall/forecast, `date.nager.at` public holidays). Any failure degrades to a
  confidence-0 "unavailable" evidence item rather than raising; force-disabled under the `offline`
  profile.
- `context_question.py` -- decides whether the one context question Care+ ever
  asks unprompted is worth asking, given the `PersonState` the policy ladder already produced.
  Never re-runs or imports the ladder.
- `ontology.py` -- the one place that knows what "walk" means: `ActivityType`,
  `ActivityFamily`, `Format` and a single alias table (English, Singlish, Chinese) shared by the
  keyword parser, catalogue normalisation and the tests that stop the two drifting apart. The LLM
  tool enum is generated from it at import; `normalise` checks a hand-authored catalogue label
  against a listing's own words and never writes one.
- `intent.py` -- the deterministic, no-model text -> `ActivityIntent` parser; the
  offline/always-available path for the user-initiated activity search. A negated phrase produces
  an `excluded_*` entry and never a positive value on any axis, nor its complement.
- `activity_search.py` -- the user-initiated loop's deterministic core:
  `filter_candidates`, `reasons_for`, `rank_candidates`. Pure functions, no DB or network access;
  their output is the allow-list the activity-ranking guardrail enforces.

  The rule that decides what belongs in the filter rather than the ranker: **a hard rule exists
  only where a mismatch is a barrier the person cannot cross -- a distance they gave as a number,
  a day, a time window, an environment, company, capacity, language -- or where they explicitly
  excluded something. Everything else is soft. A hard rule is never re-scored softly; a soft axis
  is never promoted to a filter.**

- `replanning.py` -- `notices_for` detects a planned activity that has disappeared from the
  catalogue, is now full, or (on a rainy day) is outdoors, and proposes a like-for-like
  alternative through the same filter/rank pair; `sentence_for` owns the wording for each reason
  code and `notice_for_offer` renders an offer the server already recorded. Never mutates a plan
  itself. See [Replanning](#replanning).
- `follow_up.py` -- `observe_effect`: describes, but never claims to cause, what a
  person's activity did in the days after one piece of outreach.
- `outreach_content.py` -- the fixed, reviewed "tell me more" copy behind an
  intervention. Never model-generated; this is the one screen that asks someone to move their body.
- `fixtures.py` -- synthetic persona histories, the activity catalogue fixture, and
  demo-reset content. The single source of the deterministic Mdm-Lim-and-friends dataset.
- `runtime.py` -- `validate_runtime`: refuses to start on a misconfigured profile. See
  [Runtime profiles](#runtime-profiles).
- `config.py` -- `Settings` (pydantic-settings): every environment-driven flag,
  including the runtime profile and the LLM/agent knobs.
- `auth.py` -- Supabase JWT verification (JWKS fetch/cache, ES256/RS256/HS256) and the
  `Senior`/`Coordinator`/`DemoOperator`/`AnyUser` FastAPI dependencies `main.py` routes depend on.
- `local_time.py` -- the one place "morning"/"afternoon" is computed from a person's
  local wall clock rather than UTC (everything is stored in UTC).
- `logging_config.py` -- the structured JSON log formatter `main.py`'s request-logging
  middleware uses.
- `migrations.py` / `schema_revision.py` -- run `alembic upgrade head`
  programmatically at API startup, and read the Alembic head revision for `/ready`.
- `openapi.py` -- `python -m silverloop.openapi`, writes `app.openapi()` to
  `openapi/silverloop.json`; wired to `pnpm client:generate`.
- `scenarios.py` -- `run_scenario`: replays one YAML scenario file's events through a
  repository for `pnpm test:scenarios`.
- `seed.py` / `smoke.py` / `supabase_smoke.py` --
  seed every curated persona; a black-box HTTP smoke test; the Supabase-specific equivalent run
  before a shared-profile deploy.
- `setup_demo_accounts.py` -- admin CLI provisioning demo Supabase accounts and
  linking them to `person_id`s; refuses to run under `APP_ENV=production` without
  `--allow-production`.

Subpackages:

- `adapters/` -- the provider-neutral ingestion boundary (`AdapterBatch`, `CanonicalDailyMetric`,
  `SourceClassification`). `synthetic.py` is the default, deterministic fixture history;
  `csv_sample.py` reads a pre-aggregated CSV; `apple_export.py` parses a real Apple Health
  `export.xml` -- proof that real-world ingestion works, not a live HealthKit integration.
- `agent/` -- the bounded LLM planning loop, gated by `Settings.llm_enabled` (default `false`).
  `planner.py` holds `plan_outreach` (which permitted outreach candidate to offer, and how to word
  it) and `plan_activity_ranking` (reordering a user-initiated search's already-filtered options);
  `intent_planner.py` holds `plan_intent`, the model-backed alternative to `intent.py`'s
  deterministic parser; `guardrails.py` is the actual security boundary -- plain, deterministic
  Python that rejects any proposal using clinical/emergency language or naming a candidate outside
  the permitted set, with no model call of its own; `tools.py` is the read-only tool surface the
  model can call; `constants.py` fixes model ids, the iteration ceiling and message-length limits;
  `models.py` defines the typed audit records (`AgentRun`, `AgentToolCall`, `PlannerMode`). See
  [The activity-planning subsystem](#the-activity-planning-subsystem).

## Request lifecycle

The Vue app calls a route in `main.py` (or `family_routes.py`) with Axios, through
`apps/web/src/services/careApi.ts`, typed with the generated client's types (`libs/api-client`).
The route depends on one of four FastAPI dependencies from `auth.py` (`Senior`, `Coordinator`,
`DemoOperator`, `AnyUser`), which verifies the bearer JWT and injects a typed `CurrentUser` -- or,
with `AUTH_ENABLED=false`, substitutes a fixed synthetic identity per role and skips verification
entirely. Person-scoped routes additionally call `check_person_scope`, which 404s (not 403) a
senior reading anyone but their own linked person, and is a no-op for coordinator/demo-operator
callers and for the whole app when auth is disabled. See "Auth, in brief" in `docs/api.md` for the
full role table.

The route then calls a method on the injected repository
(`Annotated[SilverLoopRepository, Depends(get_repository)]`), which at runtime is always the one
`SqlAlchemyRepository` instance held on `app.state.repository`. `SilverLoopRepository` is a
`Protocol`, not a base class, so this boundary is structural: `main.py` never imports SQLAlchemy.
Inside the repository, every mutating call opens one `session.begin()` transaction and every read
opens a plain session; domain rules are enforced there and surfaced as `KeyError` (not found),
`ValueError` (a business-rule conflict), `RuntimeError` (a person who exists but has no active,
seeded scenario run) or, on a racing write, `IntegrityError`. Most routes map these locally with
their own `try`/`except` for a route-specific message; `main.py` also registers three app-level
fallback handlers (`register_exception_handlers`) that catch whatever a route's own handling did
not -- `KeyError` -> 404, the narrow "never seeded" `RuntimeError` family -> 409, any other
`ValueError` -> 422 with `str(exc)` as the detail -- so a route that omits its own handling no
longer surfaces as a bare 500. See "Fallback error handling" in `docs/api.md` for the exact
matching rules and the one route whose gap is not an exception at all.

The response is a Pydantic model validated against `models.py` and serialised by FastAPI.
`python -m silverloop.openapi` (`pnpm client:generate`) writes `app.openapi()` to
`openapi/silverloop.json`, from which `libs/api-client/src/generated` is regenerated; `pnpm
client:check` fails CI if either artifact would differ from what `models.py` and `main.py`
currently produce. The browser types every response with that generated client's types -- never a
handwritten copy of a model type -- and makes the requests with Axios (`apps/web/src/services/`),
never Supabase directly.

## The decision path in detail

`POST /v1/simulation/advance` is the route that walks the full path below (the demo/scenario event
mechanism; see `docs/api.md` for the allowed events). `SqlAlchemyRepository.advance` synthesises
the next day's `DailyMetric` for the chosen event and, for the weather events, a `ContextSignal`.

1. **Baseline.** `analytics.analyse_signal` calls `quality.assess_data_quality` first -- the
   8-hour minimum-wear-time gate -- and only computes a baseline if that day is interpretable:
   `analytics.calculate_baseline` (28-day rolling median/MAD, an anchored reference from the
   earliest valid days on record, and the reference clamped floor `BASELINE_DRIFT_FLOOR = 0.85` so
   a baseline that has followed a sustained decline down cannot be read as normal) and a
   `SignalSummary` (`delta_percent`, `robust_z`, `sustained_low_days`, `confidence`). The reference
   itself can be re-anchored, but only by the person: once the clamp has bound for
   `CANDIDATE_BASELINE_STREAK_DAYS` (28) consecutive days, `_evaluate` asks "is this your new
   normal?" (`PersonState.pending_baseline_confirmation`); a `confirm` writes a `BaselineConfirmationRow`
   that `calculate_reference` reads back as a `ConfirmedReference` on every later evaluation, and a
   `decline` changes nothing but starts a 30-day cooldown before asking again. See
   `baseline_confirmation.py`. This is the release for the clamp above; `policy.py` is unchanged --
   confirming only changes what counts as this person's normal, never what the ladder permits.
2. **Policy gate.** `policy.decide` runs the ladder over that `SignalSummary`, as a fixed sequence
   of unconditional early returns, in this order: **consent active** -> **data quality**
   (`safe_to_interpret`) -> **confidence** (`>= 0.45`) -> **rain context** (`context.rainy` and
   fewer than 2 sustained low days) -> **baseline too small to be meaningful** (a positive baseline
   under 500 steps) -> **severity/persistence** (`sustained_low_days >= 3` and `severity >= 40%` ->
   `COORDINATOR_REVIEW`; `>= 2` days and `>= 25%` -> `PROGRAMME_SUGGESTION`; `severity >= 20%` ->
   `GENTLE_NUDGE`; else `NO_ACTION`) -> **contact-fatigue guard** (a weekly cap of 2 contacts, or a
   3-day cooldown after an accepted suggestion), applied only inside the `PROGRAMME_SUGGESTION` and
   `GENTLE_NUDGE` branches, never at `COORDINATOR_REVIEW`. Both guards are counted in the person's
   simulated days: the cap counts interventions whose decision-evidence `observed_at` falls in the
   seven days ending today (`CONTACT_CAP_WINDOW_DAYS`), never `created_at`, so advancing a
   simulated week in a minute releases the budget exactly as living through one would. `Decision`
   has five values: `NO_ACTION`, `GENTLE_NUDGE`, `PROGRAMME_SUGGESTION`, `COORDINATOR_REVIEW`,
   `SUPPRESS`.
3. **Action.** `GENTLE_NUDGE`/`PROGRAMME_SUGGESTION` create one `Intervention`;
   `COORDINATOR_REVIEW` opens or refreshes a single `ReviewCase` per person (updated in place, not
   duplicated, so a persisting decline does not fill the queue with near-identical cards);
   `SUPPRESS`/`NO_ACTION` write no outreach at all, only the audit trail.
4. **Candidate selection.** Inside intervention creation, the per-candidate Beta-Bernoulli learner
   (`learning.PreferenceLearner`) ranks the decision's permitted candidates, and the top-ranked
   candidate and its message are computed and held as the fallback choice _before_ anything else
   runs. `agent.planner.plan_outreach` may then be consulted to choose among that same permitted
   set and reword the message (see below); on any failure to do so -- disabled, unavailable, an
   API error, an exhausted iteration budget, or no proposal -- the precomputed deterministic
   fallback is used verbatim, so `LLM_ENABLED=false` and a live provider outage take the identical
   code path.
5. **The response clock.** Before the day is decided, `advance()` closes any offer still
   `proposed` with no outcome `RESPONSE_WINDOW_DAYS` (2) simulated days after it was made:
   one append-only `no_response` outcome row with actor `system`, `status` to `closed`, and an
   `intervention_outcome_recorded` audit event whose detail says `resolved_by: response_window`.
   It is the same transition a senior's answer performs, so the trace's pending stages resolve
   instead of waiting forever, and silence reaches the learner at the half weight `learning.py`
   already gives `no_response`. It is not a decline: no decline reason, no step toward
   `DECLINES_BEFORE_SUPPRESSION`. The intervention row is locked (`SELECT ... FOR UPDATE` on
   PostgreSQL; a no-op on SQLite) in both this pass and `record_outcome`, so a person's answer
   always wins a race with the clock. The read phase commits before the planner is consulted, so
   a later write-phase failure leaves the day advanced and the resolution recorded -- the same
   property `run.current_day` already had.
6. **Outcome and learning.** A senior's outcome, follow-through and enjoyment responses feed back
   into the same per-candidate learner (`learning.record`) and the dimensional learner
   (`preferences.py`) -- never into `policy.py`. Neither learner can create, escalate, downgrade or
   suppress a decision, and neither imports from `policy.py`; they may only reorder what the ladder
   already permitted.

## The decision trace

`_build_loop_trace` in `sql_repository.py` builds one `list[DecisionTraceStep]` per `advance()`
call: **ten** stages, in this fixed order -- `observation`, `validation`, `reasoning`,
`policy_gate`, `action`, `response`, `outcome`, `follow_through`, `learning`, `audit`.
`follow_through` was inserted at order 8, between recording the tap and learning from it, when the
follow-through loop landed; the trace had nine stages before that. Each step carries a
`TraceStatus` (`completed` / `blocked` / `pending` / `not_applicable`) computed from the decision
actually reached that call, a human-readable `title`/`detail`, and an `evidence_id` pointing at the
specific evidence row it describes, so the trace is a real index into the audit trail rather than a
decorative timeline.

This shape is a contract, not an implementation detail. No screen shows the trace any more, so
it is asserted against the API response directly. The trace is returned on `AdvanceResponse.loop_trace`
and persisted verbatim as JSON on the `simulation_events.response_json` column, so
`GET /v1/simulation/latest` and `GET /v1/simulation/history` can replay a past trace after a
restart without recomputing it.

## Data model

Every table lives in `db_models.py`, owned by SQLAlchemy 2 and Alembic. Grouped by area, with
whether each is written once and never mutated ("append-only"), written once per entity and then
left alone ("write-once"), or updated in place:

- **Identity and run state.** `people` (one row per person); `scenario_runs` (one active run per
  person; `current_day`/`active` are mutated in place); `auth_user_person_links` (maps a Supabase
  `sub` to one `person_id`).
- **Sensor evidence.** `daily_metrics` (append-only; a disputed day is never edited, only annotated
  via `day_disputes`); `simulation_events` (append-only and protected from mutation -- one row per
  distinct `event_id`, replayed rather than reprocessed on a repeat call); `day_disputes`
  (append-only; the person's account is attached alongside the sensor row, never replacing it).
- **Decisions and audit.** `decision_evidence` (append-only); `audit_events` (append-only);
  `consent_evidence` (append-only -- a withdrawal is a new row, not an edit to the old one).
- **Outreach and its follow-through.** `interventions` (`status` mutated as the loop progresses);
  `intervention_outcomes` (append-only, enforced by a DB trigger that rejects `UPDATE`/`DELETE`
  outright: recording a decline reason after the fact adds a second, newer row for the same
  intervention rather than editing the first, and every reader that folds outcomes into a count or
  a learner's evidence resolves to the single latest row per intervention so the amendment is never
  double-counted); `intervention_follow_through` and `intervention_enjoyment` (write-once: a unique
  constraint on `intervention_id` enforces at most one row each).
- **Review.** `review_cases` (refreshed in place while open -- one row per person's open concern,
  not one per day it persists); `case_reviews` (append-only action log against a case).
- **Programmes and the activity catalogue.** `programmes` (the original proactive-outreach
  fixture); `activity_candidates` (the user-initiated catalogue; a separate table from `programmes`
  because its shape -- indoor/outdoor, intensity, language tags, provenance -- is wide enough that
  reshaping `programmes` would have broken the existing contract).
- **Preferences and memory.** `candidate_preferences` (a person's own explicit mute, updated in
  place, unique per `(person_id, candidate_key)`); `activity_dimension_preferences` (the learned
  dimensional signal, updated in place, unique per `(person_id, dimension, value, source)` --
  `source` is part of the key so a stated row and a learned row about the same value coexist as two
  beliefs; carries `expires_at`, `stated_text`, `first_observed_at`);
  `activity_offer_responses` (append-only: every "I'm interested" / "Not for me" on a search card,
  with reason, rank shown and the simulated day); `plan_follow_through` and `plan_enjoyment`
  (append-only, one per week-plan entry, mirroring `intervention_follow_through` /
  `intervention_enjoyment`);
  `proposed_memories` (`status` starts `pending` and becomes terminal exactly once);
  `context_question_answers` (write-once per `(run_id, question_id)`);
  `baseline_confirmations` (append-only -- both a confirm and a decline are evidence, and a later
  decision may supersede an earlier one as the person's life changes again; the most recent
  `confirm` row for a run is the reference `calculate_reference` uses).
- **Goals and the week.** `activity_goals` (updated in place, unique per `(person_id, kind)`);
  `week_plan_entries` (unique per `(person_id, day, activity_id)`, so resubmitting the same choice
  is a no-op rather than a duplicate); `replan_offers` (see [Replanning](#replanning)).
- **Review setting.** `review_threshold_proposals` and `review_threshold_decisions` (the
  coordinator's review setting; no current screen).
- **Accounts and family.** `accounts` (one per signed-up user, `senior` or `family`);
  `care_groups` and `group_members` (one group per senior; members are `pending` until approved);
  `family_pins` (hashed senior-link and join PINs, with expiry) and `pin_attempts` (wrong-PIN
  lockout); `appointments`, `availability_entries` and `helper_assignments` (the shared calendar);
  `family_activity` (the family feed: append-only, no FK to appointments, cleared only by the demo
  reset); `appointment_notes` (per-day notes on an appointment, group-only, deletable by their
  author; deleted with their appointment).

## Schema ownership

SQLAlchemy 2 (`db_models.py`) and Alembic (`apps/api/alembic/versions/`, 23 revisions) are the
schema of record for both PostgreSQL/Supabase and the SQLite test/offline
fallback; `migrations.py` runs `alembic upgrade head` at API startup. `infra/supabase/migrations`
is a **hand-maintained SQL mirror** of that schema for the Supabase project (24 files:
Alembic's own DDL plus the explicit `REVOKE`-based deny policies for the `anon` and `authenticated`
Data API roles, which do not belong in the Alembic chain because they are Supabase-platform
concerns, not SQLAlchemy ones). Being hand-written rather than generated, the mirror has
concretely diverged from Alembic before -- once by putting Supabase-platform DDL inside an Alembic
migration, and once when the fix for that over-corrected with a `FORCE ROW LEVEL SECURITY` that no
other table uses and would plausibly have denied the API's own owner-role access. A currently live
instance of the same class of drift: the mirror's
`202609060006_follow_through_loop.sql` adds an append-only trigger
(`reject_silverloop_evidence_mutation`) to `intervention_follow_through` and `day_disputes`, but
the Alembic revision it mirrors (`d4a7c1f9e2b3_add_follow_through_loop.py`) only creates the two
tables and never adds an equivalent trigger -- so those two tables are genuinely append-only on
Postgres/Supabase and not on SQLite, and nothing currently checks that they agree. `GET /ready`
compares the live database's `alembic_version` row against the repository's own Alembic head and
reports `not_ready` on a mismatch, but that only catches drift in _revision_, not drift in
_content_: two databases both stamped with the same revision can still have a mirror-only defect
that `/ready` cannot see. `docs/supabase.md` documents the mirroring duty; there is no automated
check that the mirror's DDL matches what Alembic would have produced.

## Runtime profiles

`Settings.silverloop_runtime_profile` (env `CAREPLUS_RUNTIME_PROFILE`, or the older
`SILVERLOOP_RUNTIME_PROFILE` when that is unset; default `shared`) is
validated once, at startup, by `runtime.validate_runtime` -- not re-checked per request:

- **`shared`** requires a PostgreSQL `DATABASE_URL`; `offline` requires SQLite. Either backend
  under the wrong profile refuses to start, and `shared` additionally refuses a `DATABASE_URL`
  still containing a placeholder (`PROJECT_REF`, `REGION`, `:password@`, `<password>`) rather than
  a real Supabase connection string.
- **`offline`** additionally requires `ADAPTER_MODE=fixture` and `LLM_ENABLED=false`. This is
  deliberate, not incidental: `pnpm demo:offline` is the one sanctioned non-Postgres run, and it
  exists specifically to work with no network reachable at all, so it cannot depend on a live LLM
  provider or a non-fixture adapter succeeding.
- **`EXTERNAL_CONTEXT_ENABLED`** (the live weather/public-holiday lookups in `context.py`) defaults
  `false`, and `create_app` force-disables it whenever the runtime profile is `offline`, regardless
  of what the setting says -- so the offline demo and Playwright never depend on data.gov.sg or
  `date.nager.at` being reachable.
- **`LLM_ENABLED`** defaults `false`. Unlike some historical documentation of this codebase
  suggests, this flag is not inert: `agent.planner.plan_outreach`, `plan_activity_ranking` and
  `agent.intent_planner.plan_intent` all branch on it directly, and when it is `true` with a
  reachable provider and a valid key, the model genuinely selects and words outreach, ranks a
  user-initiated activity search, and parses free-text search requests -- subject to the
  deterministic guardrail in every case. What is true is that the full demo, every test and the
  `offline` profile all run with it `false`, so the code path that ships and is exercised end to
  end is the deterministic one; a reader who has only seen the demo or the tests will only ever
  see `fallback_disabled`. `runtime.validate_runtime` refuses to start with `LLM_ENABLED=true` and
  no reachable credential (an Anthropic key, or Bedrock's ambient AWS credential chain plus a
  region), specifically so an operator cannot discover mid-demo that the planner silently fell back.
- `AUTH_ENABLED=false` is refused outright when `APP_ENV=production`.

## The activity-planning subsystem

**No current screen uses this subsystem.** It is reachable through the API (and `/docs`) only.

Commit `33ce89f` ("add activity planning backend") added the user-initiated loop described in
`docs/api.md`: `activity_search.py`, `intent.py`, `preferences.py`, `replanning.py` and
`context_question.py`, plus the routes, models and repository methods that serve
`/v1/activities/search`, `/v1/people/{id}/week`, `/v1/people/{id}/goals` and
`/v1/people/{id}/replan-notices`. It answers a different question from the policy ladder, and says
so in its own code: `policy.decide` answers "should we contact this person?", triggered by a
change in their wearable data; this subsystem answers "what should I suggest, now that this person
has asked?", triggered by the person. **It is deliberately never routed through `policy.py`** --
none of `activity_search.py`, `intent.py`, `preferences.py`, `replanning.py` or
`context_question.py` imports it, and `context_question.py`'s docstring states outright it "never
will."

What it keeps from the proactive loop is the same safety discipline, applied to a different
gate: a deterministic step runs first and is the only thing permitted to narrow the candidate set,
and a bounded, optional model may only reorder what that step already permitted, never invent a
member of it. `activity_search.filter_candidates`/`rank_candidates` are that deterministic step
here, the same role `policy.decide` plus the per-candidate learner play for outreach.
`agent.planner.plan_activity_ranking` is the optional model step -- reusing the same `PlannerState`
loop discipline, iteration ceiling and audit-trace shape as `plan_outreach` -- and
`agent.guardrails.validate_activity_order` is its guardrail, rejecting any proposed ordering that
contains a key outside the filtered set. `filtered_out` is returned to the API caller, not just
logged, specifically so "the ranker chose well" is falsifiable against what it was never shown.
`replanning.notices_for` and `context_question.question_for` sit downstream of this subsystem and
also never import `policy.py`: the former proposes a replacement for a plan the world invalidated
(and honours the person's own recent "not for me" on a listing, so a declined option is never the
replacement), the latter decides whether one clarifying question is worth asking, and neither can
gate, escalate or suppress anything either.

**The ranking pipeline** (`activity_search.py`, pure): hard filter -> six named, bounded factors
(`RANKING_WEIGHTS`: intent, preference, engagement, repetition, context, friction) -> sort on
(tier, weighted total, matched axes, distance, title) where the tier is `request_fit + repetition`
-- what the person asked for, less what they just said no to -- so no combination of learned
preference, history, weather and distance can lift a weaker match past a fuller one, and only the
person's own recent "not for me" can pull a matching listing down -> series dedupe (the best
session of a programme keeps its place; the others sit below the top three, `series_deferred`) ->
one diversity swap (`variety_promoted`, within `DIVERSITY_SCORE_MARGIN`, and only within a tier)
-> top K -> optional bounded LLM reorder or narrow of the shown K. The intent factor is computed
from the complete match list, never from the three-line card.

**One responsibility per signal.** The same fact used to be scored in several places at once,
with no two of them agreeing on where the line was, so a fix in one left the others saying the
opposite. Each row below has exactly one owner:

| signal         | owned by                                            | and nowhere else                                                                                                                         |
| -------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| distance       | `travel_utility(distance, tolerance, asked_radius)` | no friction constant, no learned near/far bucket, no parser cut-off; a phrase narrows the tolerance for that request and never widens it |
| what was asked | `request_fit` (+ the hard filter for hard axes)     | an axis constrained today contributes 0 preference utility                                                                               |
| what is known  | `preference_utility` over the person's live axes    | an axis the request constrained is excluded; DISTANCE belongs to travel                                                                  |
| environment    | `preferences.environment_compatibility -> Tri`      | filter, preference reader and rain nudge all call it                                                                                     |
| this listing   | `ActivityEngagement`, series-scoped                 | the cooldown reads the same series, with a per-session override                                                                          |
| the weather    | `context`, only when the environment was left open  | no standing bonus for being indoors                                                                                                      |

**Three-valued comparison.** `Tri = MATCH | MISMATCH | UNKNOWN`; `None` on either side is UNKNOWN,
never MISMATCH. UNKNOWN is excluded from the numerator _and_ the denominator of every fit, so an
unlisted field is never a penalty -- it used to cost a whole tier, and because the tier is the
primary sort key nothing learned could lift that listing back. The count of matched axes breaks
ties, so unknown is never free either.

**Beliefs, resolved.** `preferences.resolve(rows, today, run_id)` is the only thing the ranker reads
about a person. It applies `SourceTier` (the highest active tier wins an axis outright; today's
request never enters preference utility at all), skips retracted and consumed rows, holds an
item-level answer back until a second answer about a different programme agrees with it (a repeat
about the programme of the belief's latest origin never adds evidence, even after the belief
widened), and reports contradictions rather than scoring them. Sentiment, confidence and evidence
count are three separate numbers derived from evidence for and against:
`strength = (pos - neg)/(pos + neg + 2)`, `confidence = (pos + neg)/(pos + neg + 2)`. DISTANCE and
INTENSITY are ordinal -- a `pivot` and a `direction`, not a label -- so "1.2 km was too far" is a ceiling rather than the
bucket the listing happened to fall in; a stated "near" with no number narrows the tolerance to
`preferences.NEARBY_RADIUS_M`, and a far-leaning one is never read and cannot silence it. The card
keeps the module's invariant -- every positive contribution is a shown reason -- by giving each
positive basis a line: at most three on the card face (`reasons`), and every other eligible line in
`more_reasons`, shown inside the card's "More details and reasons" disclosure, counted as
`reasons_suppressed`. Nothing eligible is dropped (2026-09-15, round 2). The `ScoreBreakdown` is
audit-only; `RankedActivity` never carries it.

**The personal world model** (`world_model.py`, pure) is a read model, not a store: typed
`PersonFact`s assembled per request from the preference rows, baseline and confirmations, context
answers, goals, mutes and outreach history, each with provenance (`explicit` / `inferred` /
`external` / `fixture`), categorical confidence, evidence count, timestamps, expiry, `contradicts`
and `stale`. Precedence between contradictory beliefs is applied once, in `preferences.resolve`,
and read from `ResolvedPreference.contradicted_by`; the model's job is to show a _live_
disagreement. A belief a statement has consumed ("That's right") is superseded, so it is absent
from the resolved set and cannot be cited -- which is what stops agreeing with an inference
manufacturing a contradiction with it. The fixture biography is
labelled `fixture` and never gates anything -- in particular it never silences the one context
question, which an earlier guard had made unreachable for every demo persona. `GET
.../world-model` is scoped by _identity_ (`check_person_scope`), not by role: with auth enforced,
only the senior it belongs to can call it, so a coordinator only ever sees `WorldModelQuality`
counts (`/v1/metrics`). With `auth_enabled=false` -- every build and demo running today -- that
same identity check passes for whichever caller `require_senior` returns, so any caller can read
the full envelope, stated text included. No safety or consent rule
reads role, so this is not a policy gap; it is a reason to treat "coordinators never see the
facts" as a property of an authenticated deployment, not of this build as shipped.

## Replanning

**No current screen shows replan offers.** They are still written inside `advance()`.

The one place the product changes a plan a person already made, and the one place it must never do
so quietly. The loop is: the world changes -> an offer is recorded -> the person is asked -> they
answer -> the answer is recorded.

**The offer is written where the change is.** `advance()` applies the world change (a listing
filling up, the day rolling forward, the forecast turning) and, in the _same transaction_, runs
`replanning.notices_for` over the active run's upcoming plans and writes one `ReplanOfferRow` per
notice plus a `replan_offered` audit row. An offer therefore cannot exist without the fact behind
it. `reason` is a closed vocabulary -- `full`, `cancelled`, `weather` -- and it is a code, never
the sentence a person reads.

**The plan it looks at is the active run's.** A demo reset rewinds the simulated calendar, so a
dead run's plan falls inside the live week again; read person-scoped, a dead story's outing
decided which listing the live one marked full (ADR 0004's rule, applied here too).

**`weather_turns` changes no listing.** It used to flip `availability` to `full`, which put a
fabricated catalogue fact ("fully booked") on the senior's screen to stand in for a context one.
It now only sets the rain context, and the offer carries reason `weather`.
`programme_becomes_full` still marks availability, because that one genuinely is the catalogue
changing.

**Nothing is replaced silently.** `GET /v1/people/{id}/replan-notices` reads the open offers (the
reason is the recorded one; only the alternative is recomputed, so a listing that has since filled
up is never still handed to someone). `POST .../week/{plan_id}/replace` plans the replacement
through the same `_plan_activity_in_session` any other plan uses -- same session-day, week and
availability rules -- sets `replaced_reason` and `replaced_by_plan_id` on the old row, resolves the
offer `accepted` and audits `replanned`. `POST .../replan-offers/{offer_id}/decline` resolves
`declined`, audits `replan_declined`, and leaves the plan alone: declining a replacement is not
declining the outing. An offer whose day passes is closed `expired`, or `no_alternative` when
nothing similar was ever found.

**A replaced session is never asked about again.** `_week_plan_model` keeps the row (it is how the
week says what happened) but never marks it `awaiting_report`, a follow-through against it is
refused, and `plans_due` skips it -- closing the "did you get a chance to go?" about a session that
was cancelled under the person. `/v1/metrics` carries `replans_offered`, `replans_accepted` and
`replans_declined`; the two answers do not sum to the first, because an offer can still be open.

No model ranks a replacement: the alternative comes from the same deterministic
`filter_candidates`/`rank_candidates` pair the search uses, and the audit row says so
(`alternative_rank_basis: "deterministic"`).
