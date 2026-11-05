# ADR 0004: Run-scope `activity_dimension_preferences` instead of deleting it on reset

Status: Accepted. Losing cross-run comparison is accepted for the proof of concept;
the append-only design remains the path if that is ever needed.

## Context

`SqlAlchemyRepository.reset()` rewinds the simulated calendar to the fixture's anchor day and
starts a new `ScenarioRunRow`. Until this change it also deleted every
`activity_dimension_preferences` row for the person being reset -- the only place in the
repository that destroyed derived domain state outright. Every other piece of derived state
(interventions, outcomes, offer responses, plan follow-through, audit events, `candidate_preferences`
outreach mutes) either stays untouched by reset or is read per-run through an existing `run_id`
foreign key (`activity_offer_responses`, `week_plan_entries`, `plan_follow_through`,
`plan_enjoyment`; see `SqlAlchemyRepository._activity_engagement(session, person_id, run_id)`).
(That claim about `week_plan_entries` was true only of `_activity_engagement` when it was written;
see the amendment at the end of this ADR, which makes it true of every reader and writer.)

`activity_dimension_preferences` had no `run_id` at all. One row exists per
`(person_id, dimension, value, source)`; `source` is one of:

- `senior_statement` -- written only by `state_preference` / `_confirm_dimension_preference`, when
  the person themselves says "avoid outdoor activities" (optionally `until` a day) via
  `PUT /v1/people/{id}/activity-preferences/{dimension}/{value}`. Full strength (+1.0/-1.0),
  `confirmed=True`, and it is the only source that can ever carry `expires_at`.
- `decline_reason` / `inferred` -- written by `_apply_activity_decline` / `_apply_activity_enjoyment`
  (`preferences.py`'s `apply_decline`/`apply_enjoyment`) from a "not for me" reason or an enjoyment
  report. Grows in magnitude with `observations`, never reaches full strength, never carries
  `expires_at` (confirmed by reading every call site in `preferences.py`: neither function ever
  sets that field).

The reset code's own comment gave the reason for deleting the whole table: a preference with
`expires_at` would "lapse against the wrong calendar" once the calendar rewinds, and the world
model would show beliefs from a story that no longer exists. That claim is correct, and a first
version of this ADR under-weighted it: `expires_at` is compared against the _simulated_ calendar
(`_preference_expired` reads `run.current_day`, never the wall clock), and `reset()` always rewinds
`current_day` to the fixture's fixed anchor day (`date(2026, 7, 21)` for the default persona,
`fixtures._mdm_lim_history`; `date(2026, 5, 1)` for every other persona,
`fixtures._generic_persona_history`) -- which is _behind_ almost any day a statement could have
been timeboxed against. A first version of this change kept a time-boxed statement's `run_id` at
`null` on the theory that an absolute `expires_at` "means the same thing regardless of which run is
active." That is false whenever the statement had already lapsed before the reset happened:
state "avoid X until day 3", let the story run to day 10 so it genuinely expires, then reset --
`current_day` falls back to the anchor, _before_ day 3 again, and a calendar-only check reads the
row as not-yet-expired and brings it back. Ranking and the world model then honour a promise the
person had already finished keeping. This is pinned by
`test_a_reset_does_not_resurrect_a_time_boxed_statement_that_had_already_lapsed`, written first
against the naive rule and confirmed to fail exactly this way before the fix below.

Reading `_activity_engagement`, `state_preference`, `_confirm_dimension_preference`, the world
model (`GET .../world-model`) and the two ranking read paths
(`search_activities`, `_finalize_intervention`'s outreach ranking) confirmed every one of them
already has an active `ScenarioRunRow` in scope at the point it reads or writes this table, the
same way the already-run-scoped tables do.

## Options considered

**(a) Append-only preference observations with `run_id`, posterior computed per person+run.**
Rejected. This is the shape `activity_offer_responses` already uses, but
`ActivityDimensionPreferenceRow`'s own docstring is explicit that this table is "deliberately not
append-only": `apply_decline`/`apply_enjoyment` already compute the next `strength`/`observations`
incrementally in Python (`preferences.py`, `_weak_negative_strength`), and `_persist_dimension_preferences`
writes that single number back in place. Making the table append-only would mean either
duplicating that incremental math as a SQL aggregate (a second implementation of the same rule,
guaranteed to drift) or reading the whole per-run history back out of the database to recompute it
on every read -- more code and more query volume for a demo-scale table, to solve a problem the
existing design already handles by updating in place. The one real advantage this option would
have bought -- comparing an inferred belief's history _across_ runs -- is one the chosen option
gives up; see Consequences.

**(b) A simple `run_id` column on the existing updated-in-place rows, applied uniformly by
`source`.** The right shape, but wrong granularity in two directions. Scoping every
`senior_statement` row would reproduce the exact asymmetry the ticket flags ("a stated preference
silently disappears on reset while an outreach mute survives"): a _standing_ statement ("I don't
like gardening", no `until`) is a fact about the person, not the story, exactly like a
`candidate_preferences` outreach mute, and should survive a reset the same way a mute does. Leaving
every `senior_statement` row unscoped, on the other hand, is the resurrection bug above: a
_time-boxed_ statement ("avoid until Friday") is a promise about a day on the calendar of the run
it was made in, and needs the same run-scoping an inferred row gets, for the same calendar reason.

**(c) Split by what kind of fact the row is, not only by `source`: standing `senior_statement` rows
(no `expires_at`) keep `run_id = null` and are never run-scoped; every other row -- a time-boxed
`senior_statement` (has `expires_at`) or a `decline_reason`/`inferred` row -- carries the `run_id`
of the run that wrote it and is treated as absent once that run is no longer active, regardless of
what the calendar says.** Chosen. It answers the ticket's own question -- "does a person's own
statement belong to a run at all?" -- with "only the part of it that is a promise about a day,
never the part that is simply a fact about the person": `PreferenceStance`'s own docstring already
says a person's own belief "outranks anything inferred from their taps," which argues for
`candidate_preferences`-style permanence for a _standing_ statement, but says nothing about a
_time-boxed_ one continuing to apply to a day that belonged to a different story. Run-scoping the
time-boxed case closes the resurrection bug by construction: a row that is not the active run's is
inactive before its `expires_at` is even consulted, so a rewound calendar can never read it as
"not yet lapsed."

## Decision

Add one nullable `run_id` column (foreign key to `scenario_runs.run_id`) to
`activity_dimension_preferences`. `reset()` no longer deletes rows from this table. Whether a row
is run-scoped depends on what kind of fact it is:

- A **standing** `senior_statement` row (`prefer`/`avoid` with no `until`): `run_id` stays `null`
  forever. Never run-scoped. Survives every reset; bounded only by an explicit `forget`.
- A **time-boxed** `senior_statement` row (`until` a day, so `expires_at` is set): stamped with the
  `run_id` of the run it was stated in (`_confirm_dimension_preference`). Treated as inactive once
  a different run becomes active, on top of (not instead of) the existing calendar-expiry check.
- A `decline_reason` / `inferred` row: always stamped with the run that produced it, as before.

`_dimension_rows` (`_preference_inactive`) is the one place this is decided: a row is inactive if
it is calendar-expired, **or** it is not a standing statement and carries a `run_id` that is not
the active run's. Critically, "is a standing statement" is derived from the fact itself --
`source == "senior_statement" and expires_at is None` -- never from `row.run_id is None`. A first
version of this fix used `run_id is None` as the standing test directly, which is wrong for any
row this table already held before `run_id` existed: every one of those legacy rows also has
`run_id = null`, and reading that as "standing" would have made every existing inferred belief
permanent and kept every existing time-boxed statement resurrecting after a reset -- reintroducing
both bugs run-scoping exists to close, for every row already in a shared database at the moment
this migration runs. Deriving "standing" from the row's own fields instead means a legacy or
unbackfilled row is simply, correctly, run-scoped: it has no `run_id` that equals any real run, so
it reads as inactive until new evidence on its key reattaches it to one. This is read by every
consumer of "what does this person currently hold" -- ranking, the world model,
`GET .../activity-preferences` -- so all three agree, and none of them special-case reset.

Because a legacy row would otherwise sit inactive until reused, the migration also backfills it:
where `source <> 'senior_statement' OR expires_at IS NOT NULL` and `run_id IS NULL`, `run_id` is
set to the row's person's currently _active_ scenario run, so existing data reads correctly the
moment the migration completes rather than only once new evidence happens to touch each row. A
person with no active run at the time (should not occur in practice; every reset provisions one)
is left `run_id = null` -- the read path above already treats that as run-scoped-and-inactive, so
guessing a run for it would be no safer than leaving it null, and would be a fabricated fact. Both
the Alembic migration and the Supabase mirror run the same backfill, guarded to touch only rows
still `run_id is null` so a second application is a no-op.

`FORGET` (`stance=forget`) is unaffected: it is an explicit person-initiated deletion of every row
on a `(dimension, value)` key regardless of run, which is a different, already-audited action from
the silent, blanket destruction reset used to perform.

Alembic revision `c2725d7de5df` (down-revision `c2f4a8d1e6b7`, the verified previous head) adds the
column, its foreign key and its index via `batch_alter_table` (SQLite recreates the table; Postgres
emits a plain `ALTER TABLE`). One migration covers both the standing/time-boxed split and the
inferred-row scoping -- the column and its semantics are the same `run_id`, read the same way by
`_preference_inactive`; only which rows get a non-null value at write time differs. The Supabase
mirror (`infra/supabase/migrations/202609130012_dimension_preference_run_scope.sql`) follows
`202609120011`'s guarded, idempotent pattern (`add column if not exists`, a `pg_constraint`
existence check, `create index if not exists`, a guarded `alembic_version` bump) and needs no new
RLS/deny statements: `activity_dimension_preferences` has carried both since
`202609060007_activity_catalogue.sql` and this revision alters no other table.

No `models.py` change: `run_id` is internal bookkeeping, never returned to a client, so the OpenAPI
contract and generated TS SDK are untouched and `pnpm client:generate` was not run.

## Consequences

- A demo reset keeps a person's own **standing** stated preferences across the reset that used to
  erase them, closing the asymmetry the ticket names.
- A **time-boxed** stated preference does not survive a reset, whether or not it had already
  lapsed by the time the reset happened -- it belonged to a run that is no longer active. This is
  a deliberate, narrower promise than "reset never touches a stated preference": it trades a small
  amount of continuity (a not-yet-lapsed "avoid until Friday" also disappears on an early reset)
  for eliminating the resurrection bug entirely, rather than trying to detect "did this genuinely
  lapse before the reset" with more calendar arithmetic.
- Ranking, the world model and `GET .../activity-preferences` are unaffected in the case that
  motivated the original delete: a fresh run still starts with no _inferred_ dimensional belief,
  and no _time-boxed_ stated one, from a story that no longer exists.
- `WorldModelQuality.expired_excluded` (the senior-facing "N expired and excluded" count on
  `GET .../world-model`) keeps meaning calendar-expired only. `_dimension_rows`'s inactive bucket
  is broader than that name now -- it also holds a run-scoped row that is merely stale, not
  lapsed -- so the world model assembly filters it back down to calendar-expired rows before
  counting, rather than counting the whole bucket. A stale-run row is absent from the model
  exactly like before this ADR, never shown to the senior as one more "expired" fact, and the
  count does not grow with every reset. No new field: the fix is which rows the existing field
  counts, not a new count for the new reason a row can be inactive.
- **Restarting a stale-run row in place overwrites its history, not just its visibility.** When a
  `decline_reason`/`inferred` row (or a time-boxed `senior_statement` row on the same key) is
  reused after a reset, `_persist_dimension_preferences` / `_confirm_dimension_preference` reset
  its `observations` to one and reattach it to the new run -- the old run's count is gone, not
  archived. The ticket listed comparing a belief's evidence across runs as a benefit of the
  append-only option (a); this decision does not deliver that, and cannot without changing the
  storage shape. If comparing an inferred belief's history across runs is ever needed, that is the
  point at which option (a) -- an append-only observation log, aggregated per `(person, run)` --
  should be revisited; it was rejected here only because nothing in this ticket's scope needs it.
- Rows for inferred or time-boxed preferences from a retired run are no longer deleted; they
  persist as inert audit trail until reused. For a demo-scale table (one row per
  `(person, dimension, value, source)` ever observed) this is bounded, not unbounded growth, since
  the same key is reused in place across runs rather than appended.
- `_dimension_rows`, `_activity_preferences_model`, `_persist_dimension_preferences` and
  `_confirm_dimension_preference` gained a `run_id` (and, for the last one, `current_day`)
  parameter; every call site already had an active run in scope, so no new database read was
  introduced anywhere.
- **Restating a standing statement with `until` converts it to a time-boxed, run-scoped one, in
  place.** `(person_id, dimension, value, source)` is the row's whole key -- there is no separate
  slot for "the standing version" and "the time-boxed version" of the same belief -- so saying
  "avoid gardening" (standing) and later "avoid gardening until Friday" (time-boxed) on the same
  key does not layer the second on top of the first; it replaces it, `run_id` included. The
  standing belief that used to persist forever now disappears at the very next reset, exactly
  like any other time-boxed statement, whether or not Friday has arrived. This is intended, not
  an oversight: it is the same rule `_confirm_dimension_preference` already applies to a reversed
  stance ("a change of mind is a new statement, not a stronger old one") applied to a change in
  _shape_ rather than _direction_ -- the person's most recent full statement is what the row
  records, not a merge of everything they have ever said on that key. Reverting to a standing
  statement (a later `until=None` on the same key) restores `run_id = null` the same way, so the
  conversion runs both directions and neither is a dead end.

## What would change our mind

If a future "start a completely new persona" reset needs to feel like a genuinely blank slate (no
residual voice from a previous demo persona's own words), a _standing_ `senior_statement` row
surviving across that kind of reset would be wrong, and a distinct "hard reset" operation --
separate from the calendar-rewind `reset()` this ADR covers, and only for genuinely new person
records -- would need to also clear standing rows explicitly. That is a different operation than
the demo-story reset audited here and is deferred rather than folded into this change.

If a product need emerges to compare an inferred preference's strength or observation count across
separate demo runs (rather than only within the currently active one), the in-place restart this
ADR relies on is the wrong shape for that, and the append-only design in option (a) -- rejected
here as unnecessary complexity -- would need to be revisited.

## Evidence gathered

- `server/alembic/versions/c2f4a8d1e6b7_add_activity_responses_and_preference_expiry.py` is the
  verified current head; `c2725d7de5df` sets `down_revision = "c2f4a8d1e6b7"`.
- `preferences.py` grepped for `source=`: only `"decline_reason"` (line 306) and `_ENJOYMENT_SOURCE`
  (line 450) are ever written by `apply_decline`/`apply_enjoyment`; `senior_statement` is written
  exclusively by `_confirm_dimension_preference`, and only that path can ever set `expires_at`.
- `fixtures.py`: fixed anchor days `date(2026, 7, 21)` (`_mdm_lim_history`) and
  `date(2026, 5, 1)` (`_generic_persona_history`); `sql_repository.py:1435`,
  `next_day = current.day + timedelta(days=1)` -- one simulated day per `advance()` call, always.
  The anchor being fixed and behind any day reached during play is exactly what makes the
  resurrection bug reproducible on demand, not a rare timing accident.
- `test_a_reset_does_not_resurrect_a_time_boxed_statement_that_had_already_lapsed`
  (an API test since removed with its route): written and confirmed failing against the
  `run_id = null`-for-all-`senior_statement` version of this change (the statement reappeared after
  reset), then confirmed passing once time-boxed rows were run-scoped.
- `uv run pytest` (server): 929 passed, 8 skipped (Postgres-only, no local Postgres), 0 failed,
  after this change, the resurrection-bug fix, the architecture-review backfill/world-model fixes
  and their tests.
- `uv run ruff check .` / `uv run ruff format --check .`: clean.
- `uv run python -m silverloop.scenarios ../../scenarios`: all 15 deterministic safety scenarios
  pass unchanged (this change touches ranking-only preference bookkeeping, never `policy.py`).
- Manual `alembic upgrade head` / `alembic downgrade -1` round-trip against a fresh SQLite file
  confirmed the new revision applies and reverses cleanly, and `PRAGMA foreign_key_list` /
  `PRAGMA index_list` confirmed the FK and index land as written.
- `server/tests/test_supabase_mirror.py` (30 tests) passes unchanged against the new mirror file,
  including the "newest mirror bumps `alembic_version` to the current head" check.
- Architecture review of the integrated change found that a version of this migration without a
  data step left every existing row `run_id = null`, and that a version of `_preference_inactive`
  deriving "standing" from `run_id is None` (rather than from `source`/`expires_at`) made every
  such row read as standing regardless of what it actually was -- permanent inferred beliefs and
  resurrectable time-boxed statements, for every row already in a shared database, not only new
  ones. `test_a_legacy_null_run_id_inferred_row_drops_out_after_reset` and
  `test_a_legacy_null_run_id_time_boxed_statement_drops_out_after_reset`
  (an API test since removed with its route) insert such a row directly, bypassing every
  repository write path, and pin that the read path alone gets it right.
  `test_dimension_preference_run_scope_migration.py` steps a real SQLite database through the
  Alembic chain to `c2f4a8d1e6b7`, inserts one row of each shape by hand, upgrades to head, and
  asserts the backfill (and its idempotency on a second, direct application of the same
  statement); the Postgres mirror replay test does the equivalent against the hand-applied file.
- The same review found `WorldModelQuality.expired_excluded` counting `_dimension_rows`'s whole
  inactive bucket, which after this ADR includes a merely stale-run row -- a count that grows by
  one every time a reset retires a run with an inferred belief in it, shown to the senior as "N
  expired and excluded" (on a world-model screen since removed), contradicting
  this ADR's own claim that the world model is unaffected. `test_expired_excluded_does_not_grow_across_resets`
  (`server/tests/test_world_model.py`) pins the count staying flat across three
  decline-then-reset cycles.

## Amendment: `week_plan_entries` is run-scoped too

The Context section above listed `week_plan_entries` among the tables "read per-run through an
existing `run_id` foreign key". That was true of exactly one reader,
`_activity_engagement`. `_week_plan_model`, `_owned_plan`, `_plan_activity_in_session`'s existing
lookup and `replan_notices` all read the table by `person_id` alone, and
`db_models.WeekPlanEntryRow`'s own docstring said the opposite of this ADR: "a plan is the
person's, not one scenario run's".

Person-scoping was not a defensible alternative reading; it was a bug, and the security audit
reproduced it twice. Because `reset()` rewinds the simulated calendar to the fixture's anchor day,
a dead run's plan days fall inside the live week again. The senior's week showed outings the new
run never made (while the already-run-scoped `metrics.activities_planned` said none existed);
those entries accepted `went` and `enjoyed`; and `_apply_activity_enjoyment` wrote the resulting
`social` and `timing` beliefs into the **new** run's `activity_dimension_preferences` -- the exact
cross-run contamination this ADR exists to prevent, arriving through a table the ADR had already
declared safe.

Resolved the way the rest of the ADR resolves it:

- every plan reader and writer filters on the active run;
- `_owned_plan` raises `KeyError` (404) for a plan from a dead run, the same non-oracle answer
  `decide_proposed_memory` gives a stale proposal -- not a `ValueError` naming the old run;
- the unique key moves from `(person_id, day, activity_id)` to
  `(run_id, person_id, day, activity_id)` (Alembic `a1d5f3b87c46`, mirrored in
  `infra/supabase/migrations/202609130013_week_plan_run_scope.sql`). Without that move the
  run-scoped readers would have made the product worse, not better: the dead run's row still
  occupied the person-scoped key, so the live run's insert of the same choice was rejected by the
  database and "add to my week" failed for a week that showed nothing.

The rows themselves are still never deleted; they belong to the story that made them.
`WeekPlanEntryRow`'s docstring now says so.

Pinned by `server/tests/test_stale_run_boundary.py` (week-plan section: invisible after reset,
404 on follow-through and enjoyment, preferences unmoved, the same choice re-plannable in the new
run, a same-run plan unaffected) and `server/tests/test_week_plan_run_scope_migration.py` (the
old key rejects the live run's insert, the migration widens it without disturbing existing rows,
within-run duplicates are still rejected, the downgrade narrows it back).
