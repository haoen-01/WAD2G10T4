# Verification strategy

## Gates

`pnpm verify` runs formatting, linting, TypeScript/Python checks, unit/API tests, Playwright
browser/API tests, YAML safety scenarios and production builds. GitHub Actions installs pinned
Chromium and runs the same categories on pushes and pull requests. Since PR #62 the CI `verify` job runs
`pnpm test` with `NX_PARALLEL=1`, one test target at a time, because running the API suite at the same
time as the browser suite starved the e2e dev server on a hosted runner. The job timeout is 30 minutes,
and Playwright results are uploaded when the job fails or is cancelled.

A separate `postgres-integration` CI job starts a disposable PostgreSQL 17 service and runs
`pnpm test:postgres`. Local execution requires `SILVERLOOP_POSTGRES_TEST_URL`; the database name must
contain `test`, which prevents the test from targeting the normal Supabase `postgres` database.

`apps/api/tests/test_query_counts.py` pins how many SQL statements each person read issues (the
senior's `/state`, and the metrics and world model `repository.metrics()` assembles). Against the
shared database each statement is a round trip to the pooler, so query count drives latency. Every
read must stay within its ceiling in `_CEILINGS`, measured on six people with 23 days of history,
and must use one pooled connection. The counts also must not grow with the data: a person read must
issue as many queries for 7 days of history as for 23. A new per-intervention query therefore fails
a test. Raising a ceiling needs review. Everything runs on in-memory SQLite, so the tests count
round trips but do not time them. (The coordinator caseload reads it also measured went with their
routes in step 7.)

Engine and pool options for a server database (`_engine_options`) are covered in
`apps/api/tests/test_engine_options.py`. That test builds the engine without connecting to a
database.

## Browser and web unit tests

The Playwright suite in `apps/e2e/tests/` drives the real Vue app against the real API (SQLite,
fixture adapters, `LLM_ENABLED=false`). Each file covers one area:

- `loop.spec.ts` — the watch status on Home; a simulated decline (played straight through the API,
  since there is no Simulator screen) reaches the senior, who replies; a persistent decline becomes a
  review case rather than a suggestion, checked from the API response; consent withdrawn through the
  API shows on Home; an unknown address shows the not-found page.
- `groups.spec.ts` — sign-up as senior or family, the senior-link PIN, joining with a join PIN and
  waiting for approval, a wrong PIN.
- `family.spec.ts` — the shared calendar: appointment details, taking an appointment or stepping
  back, weekly appointments, sharing free times and painting busy hours.
- `tasks.spec.ts` — a family member creates a task, the senior ticks it off, and it shows on the
  calendar.
- `views.spec.ts` — the family sees Home, Calendar and Family; the senior sees only their own day.
- `interface.spec.ts`, `shared-look.spec.ts`, `responsive.spec.ts` — zoom, light and dark mode,
  calendar filters and keyboard use, undo, the top bar, and phone layouts.
- `public-apis.spec.ts` — the forecast and public holidays, and that Home and the calendar still work
  when either cannot be reached.
- `home-feed.spec.ts` — the seeded family feed with "Sample" tags, a check-in that shows at once and
  survives a reload, another member seeing it under the right name, a refused check-in rolled back,
  refresh every 30 s and on focus (`page.clock`), no feed request from the senior screen, and the
  percentage under reduced motion.
- `calendar-sheet.spec.ts` — at phone width: the week strip, the bottom sheet as a real dialog (focus
  trap, Escape, close button, backdrop, drag to close, focus return, `inert`, scroll lock), family
  notes added and deleted by their author only, a full day (409), keyboard Undo while the sheet is
  open, and reduced motion.
- `family-page.spec.ts` — the avatar cluster, the invite PIN readable at once (also under reduced
  motion) and the location placeholder.
- `senior-polish.spec.ts` — the senior's main actions are at least 56px tall and nothing overflows at
  150% zoom.
- `sign-in-look.spec.ts` — no horizontal overflow on the sign-in and onboarding screens at 375px,
  and large "who is signing in" choices.

Web unit tests (`node:test` over `apps/web/src/lib/*.test.ts`, `pnpm --filter ./apps/web test`)
cover the pure logic behind the screens: activity, calendar, coverage, family (including the
temporary-id helpers for availability saves), the family feed's sentences and state, appointment
notes, the week strip, motion tokens, PIN countdowns, holidays, ICS export, planner, tasks and daily
tasks, today, view mode, wearable, weather, labels, date formatting, API errors, current user and
the route guard.

## The recorded LLM transport

`tests/test_recorded_client.py` covers the `recorded` LLM provider without calling a model: request
keying, a miss degrading to `fallback_error` named `RecordingMiss`, record mode refused under CI, the
client-factory branch, the offline-profile runtime rules, intent telemetry, the guardrail rule table
and the LLM cost counters. It writes its own small synthetic recordings into a temporary directory;
none are committed.

## The response clock

An offer nobody answers is closed as `no_response` two simulated days after it was made (see
`docs/api.md`, "Silence resolves itself"). `apps/api/tests/test_response_clock.py` pins it at the
contract: open inside the window with `awaiting_reply_until` stated; closed once the window
passes; a recorded answer never overwritten; withdrawn offers never counted as silence; a replayed
`event_id` never resolving twice; the audit event by `system` naming `resolved_by`; the candidate
posterior moving by exactly one `no_response` weight and only once; three silences never muting a
candidate the way three declines do; a late reply told the offer closed rather than "already
recorded"; the two metrics counters; the trace's response stage naming the date. The same file
asserts the contact cap counts the person's simulated week (nine days of advances in one second
release the budget) and still binds inside it.

Scenario YAML can now assert outcomes as well as decisions: an optional `expected_outcomes:` list,
one entry per intervention created (oldest first, `null` for one still open), checked by
`scenarios.py` after the decisions. `05_sustained_decline.yaml` asserts `[no_response, null]`, and
`15_contact_cap_counts_simulated_days.yaml` -- two contacts, six recovery days, then a mild dip
that is permitted a nudge rather than `suppress`ed -- asserts `[no_response, no_response, null]`.

## The follow-through loop

Outreach used to end at the sentence. A person tapped "Yes, tell me more", was shown nothing more,
and the tap was recorded as a success. The tests added with the follow-through loop cover the three
beats that were missing and, more importantly, the integrity claim underneath them.

**`test_learning_weights.py` — acceptance is not success.** `PreferenceLearner` used to count
outcomes, so an `accepted` was one success exactly like a `coordinator_resolved`. It is now
weighted, and the tests assert the _relationships_ rather than the constants, so a retune of
`_OUTCOME_WEIGHTS` has to preserve the product claim or fail:

- A bare tap moves the posterior at least twice less than a reported completion, and no run of taps
  ever overtakes a single completion.
- `deferred` moves nothing in either direction, and sits strictly above silence, which sits strictly
  above a refusal.
- A follow-through **supersedes** the acceptance weight rather than stacking on it — one
  intervention contributes at most one unit of evidence, asserted against both the superseded value
  and the stacked value a naive `+=` would produce.
- The differentiating property, asserted directly: a candidate everybody taps and nobody does ranks
  **below** one that is offered a third as often and actually carried out. The same test asserts the
  counterfactual — ranking on acceptance alone inverts the order — so the property cannot pass for
  the wrong reason.
- An **exhaustiveness guard** over both weight tables. `record` returns silently for an outcome it
  has no weight for, which is the right runtime behaviour and exactly the wrong failure mode to
  leave unguarded: a new `OutcomeKind` or `FollowThrough` member would otherwise ship, raise
  nothing, log nothing, and simply stop being learned from.

**`test_follow_up.py` — descriptive, never causal.** `observe_effect` reads days a person lived for
a hundred reasons and puts them next to a text message, so most of these tests are about what it
must refuse to say. It reports itself unavailable below two valid-wear days after the outreach;
`returned_toward_usual` requires **both** a rise and a landing near the anchored reference, so
500 → 900 steps against a 4,000-step reference is "a little higher" and never "back to usual";
low-wear days are excluded from both windows, and the outreach day itself belongs to neither. A
parametrised test walks every reachable path — no history, nothing before, nothing after, too few
after, all low wear, a rise, a fall, no change — and asserts the caveat is present on all of them.
There is no code path that produces a number without the sentence saying a single record cannot
show cause.

**`test_follow_through_api.py`.** `deferred` is accepted and audited while coordinator-only
outcomes are still refused. Three declines suppress a candidate deterministically, and — the edge
case that decides whether suppression is a feature or an outage — when **every** candidate for a
decision is muted the result is an audited `NO_ACTION` with a reason naming the person's own choice,
never a crash and never a silent skip. Suppression is asserted to narrow the permitted set without
ever raising a decision rung. (The follow-through, follow-up, enjoyment, mute and day-dispute
routes, and `test_follow_through_ownership.py` with them, went in step 7; a mute or a dispute
`advance` still reads is written as a row through `tests/row_fixtures.py`.)

**Browser.** `apps/e2e/tests/loop.spec.ts` drives the real Vue app against the real API (SQLite,
fixtures, sign-in off). The follow-through screens tested by the former browser specs are not part
of the current web app; the API behaviour above is still covered by the API tests.

## Backend features with no screen

Step 7 removed the routes no screen used. What `advance` still runs of those features -- the review
setting's daily checks, system-closed review cases -- keeps its tests. State that only a removed
route used to write (an approval, a coordinator review, a week plan, a context answer) is written
as a row by `tests/row_fixtures.py` or a file's own fixture:

- `test_review_threshold.py` — every guardrail rule pinned pass and fail, the live-setting fold,
  expiry, reconfirm, the fixed-rule proposer, notice wording against the senior vocabulary.
- `test_review_threshold_api.py`, `test_review_threshold_checking.py` — what `advance` does with an
  approval on record: expiry, the shadow check, far-more-severe reverts, the checking-period close,
  write-ups, the senior notice, consent rejecting an open proposal, run-row lock ordering.
- `test_threshold_planner.py` — the agent on fake transports: revision, cap, every fallback, fencing,
  the tool surface and the prompts.
- `test_review_threshold_postgres.py` (gated on `SILVERLOOP_POSTGRES_TEST_URL`) — the run lock
  serialises writers without blocking a child insert.
- `test_review_context_gap_contract.py`, `test_review_context_gap_migration.py` — the evaluation's
  authored-metric seam, and Alembic `7c3e9a1f4b28` up and down.
- `test_stored_state_compat.py` — a legacy snapshot without `decided_by_gate` returns a classified
  `stored_state_incompatible` on replay and recovers on reset. It also checks that server validation
  errors are `internal_error` 500s while request validation stays a 422.

## What the tests establish

- Personal median/MAD baseline calculations behave deterministically.
- Missing wear-time and rain reduce confidence or prevent premature action.
- Revoked consent always blocks outreach.
- The intervention ladder reaches human review only after sustained decline.
- Contact caps do not suppress a genuine no-action/recovery decision, but do block excess messages.
- The FastAPI contract creates review evidence and returns the coordinator queue.
- Client event IDs are idempotent across process restarts and cannot be reused for another event.
- Every `POST /v1/simulation/advance` response carries the full ten-stage decision trace
  (`follow_through` sits at order 8, between recording the outcome and learning from it); there is
  no Simulator screen to view it in any more, so this is asserted against the API response directly.
- Stale programme fixtures produce an audited `NO_ACTION`, not an outdated suggestion.
- A decision with every candidate muted also produces an audited `NO_ACTION`, with a reason naming
  the person's own choice.
- Duplicate outcomes are rejected without applying preference learning twice, and a follow-through
  is recorded once per intervention or not at all.
- Acceptance moves the preference posterior far less than a reported completion, and a candidate
  with high acceptance and low follow-through ranks below one with the reverse.
- Every `OutcomeKind` and `FollowThrough` member has a learning weight, so a new member cannot
  silently stop being learned from.
- Every follow-up observation carries its non-causal caveat, including the unavailable ones.
- "Yes, tell me more" leads to fixed, reviewed content on the senior surface, and that content
  carries no coordinator vocabulary or raw figures.
- A real Chromium session connects a simulated decline (played through the API, not a Simulator
  screen) to the senior's reply, and a persistent decline reaching `coordinator_review` is checked
  against the API response alone -- there is no Care Team screen in the current web app to review it
  from. Consent withdrawn through the API shows on the home overview.
- Family members can join a care group with a PIN and approval, share the calendar, take or step
  back from an appointment, and share when they are free; each change is saved by the API and seen
  by the others.
- The Vue app typechecks (`vue-tsc`, with unused imports as errors) and builds for production
  (`vite build`).
- PostgreSQL applies the Alembic head, preserves idempotent state across repository restarts,
  enforces consent withdrawal and rejects mutation of append-only decision evidence.
- The intent factor is scored from every matched axis, never from the three-line card; a fuller
  match is never overtaken by learned preference, weather, history and distance combined; only
  the person's own recent "not for me" can pull a matching listing down; the top three are never
  three sessions of one programme; every positive contribution is a reason on the card face or in
  `more_reasons` (shown when the card is opened, counted as `reasons_suppressed`), and a final
  entry never has more than three face lines; one decline is charged once while its cooldown runs.
- A stated preference supersedes inferred rows on its dimension rather than averaging with them;
  an enjoyment report supersedes attendance in the outreach learner; a coordinator closing a case
  moves nothing; three `bad_day` declines never mute a candidate.
- The quiet-day question is reachable for every persona (the fixture biography never silences
  it), and its answer is a fact about one day in the world model.
- A racing double tap is a 409; the consent audit records the reason's length, never the reason;
  the request log carries the route template, never the path.
- The activity planner's allow-list is exactly the shown set; person text and catalogue titles
  reach a prompt fenced and labelled as data, and a poisoned title, a "SYSTEM:" directive or a
  forged closing fence cannot add, drop or reorder outside the allow-list.
- Every ORM table has a deny policy in a Supabase mirror file, and the newest mirror advances
  `alembic_version` to the repository head.

## What the tests do not establish

- Clinical validity, fall detection accuracy or improved health outcomes.
- Healthy 365 API access or government endorsement.
- Real AAC programme availability.
- Fairness across demographic groups from synthetic data.
- Production security, durability or emergency response suitability.
- That outreach causes activity to change. `FollowUpObservation` describes what one person's days
  did around one suggestion and says so on every result; it is not evidence of effect, and the
  tests assert the caveat rather than any causal claim.
- That the follow-through weights are correctly calibrated. The tests fix the _ordering_ the
  product depends on — a completion outranks a tap, a deferral moves nothing — not the numbers,
  which are a design choice made without outcome data and would need a field pilot to justify.
- That people report follow-through honestly, or at all. Every follow-through in the suite is
  synthetic and submitted by the test; nothing here establishes a real reporting rate, and
  `None` is deliberately indistinguishable between "not asked" and "chose not to say".
- That candidate suppression matches what a person actually wants. Three declines is a chosen
  threshold, not a measured one.

Those claims require authorised data, ethics/privacy review, field pilots and outcome evaluation.

Human-only checks are kept separately in [`manual-ui-checklist.md`](manual-ui-checklist.md).
