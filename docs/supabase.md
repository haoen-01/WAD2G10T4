# Supabase PostgreSQL shared runtime

Care+ uses Supabase PostgreSQL for shared development and deployment. SQLite is retained only
for automated-test isolation and the explicit emergency offline demo. FastAPI remains the only
domain gateway: the Vue browser application must not read or write these tables through the
Supabase Data API.

## Applied schema

The remote project currently has the migrations in [`infra/supabase/migrations`](../infra/supabase/migrations):

1. `202608200001_silverloop_core.sql` creates the SQLAlchemy/Alembic-compatible domain schema,
   evidence triggers and the Alembic revision marker.
2. `202608200002_explicit_browser_denial.sql` adds explicit deny policies for the `anon` and
   `authenticated` Data API roles.
3. `202608200003_ingestion_confidence.sql` persists canonical adapter confidence and advances the
   Alembic marker.
4. `202608200004_simulation_event_idempotency.sql` stores each browser event and its response once,
   protects that evidence from mutation and advances the Alembic marker.
5. `202609020005_auth_user_person_links.sql` maps Supabase auth subjects to internal person
   records, adds explicit deny policies for the `anon` and `authenticated` Data API roles and
   advances the Alembic marker.
6. `202609060006_follow_through_loop.sql` adds the follow-through loop: an outcome `reason`
   column, `intervention_follow_through`, `candidate_preferences` and `day_disputes`, their
   append-only triggers and deny policies, and advances the Alembic marker.

All public tables have row-level security enabled. Decision, consent, outcome, review and audit
evidence reject updates and deletes at the database layer.

> **Known drift, 2026-09-04.** `auth_user_person_links` reached the live project through a local
> `alembic upgrade` rather than through the SQL mirror above, so the mirror file has never been
> replayed there and Supabase's own migration tracker lists only the first four. The live table
> therefore has RLS enabled with **no policy**, and the security advisor reports
> `rls_enabled_no_policy` against it. RLS with no policy already default-denies, so this is a
> hardening gap rather than an exposure — the Data API roles are also explicitly revoked. Close it
> by running the deny policy from `202609020005_auth_user_person_links.sql` against the project:
>
> ```sql
> create policy deny_browser_access on public.auth_user_person_links
> for all to anon, authenticated using (false) with check (false);
> ```
>
> The live table additionally carries `FORCE ROW LEVEL SECURITY`, which the mirror deliberately
> omits. It is inert here because Supabase's `postgres` role has `BYPASSRLS`, but it is drift.

> **Known drift, 2026-09-06 — the same failure a second time.** `202609060006` could not be
> applied as written: `alembic upgrade head` had already reached the project, so the tables and the
> `intervention_outcomes.reason` column existed and the mirror's first statement failed with
> `42701: column "reason" ... already exists`. Supabase runs a batch in a transaction, so that
> attempt rolled back cleanly and applied nothing.
>
> The live tables were confirmed as `rls_enabled = false`, `policies = 0`, `triggers = 0`. Schema
> landed; security posture did not. Remediated by running the mirror with its `create table` and
> `alter table ... add column` statements stripped out, leaving only the triggers, RLS enablement,
> revokes and deny policies.
>
> **This has now happened twice, for the same structural reason**, and it will keep happening: the
> API lifespan runs `alembic upgrade head` on startup, so merely pointing the shared profile at
> Supabase silently applies the Alembic half of any pending migration and permanently makes the
> mirror unrunnable as written. Alembic is the faster path and it wins by default.
>
> **From `202609120011_activity_responses.sql` onward the mirror is written idempotently** -- the
> constraint swap is guarded by a `pg_constraint` lookup, columns use `add column if not exists`,
> tables `create table if not exists`, and triggers and policies are guarded -- so it can be
> replayed over an Alembic-created schema without a partial-failure rollback. The three tables it
> adds (`activity_offer_responses`, `plan_follow_through`, `plan_enjoyment`) are person-scoped and
> one carries a free-text note: until the mirror is applied, an API start against the project
> leaves them created by Alembic **without RLS**. Apply the mirror first, or immediately after.
> `apps/api/tests/test_supabase_mirror.py` asserts every ORM table has a deny policy in some
> mirror file and that the newest mirror advances `alembic_version` to the repository head, so a
> new table cannot be added without its mirror.
>
> Two ways to stop it, neither yet done. Apply the mirror to Supabase _before_ any API process
> starts against it; or make each mirror idempotent (`add column if not exists`, `create table if
not exists`, and policy/trigger creation guarded by a catalogue lookup) so it can be replayed
> over an Alembic-created schema without a partial-failure rollback. The second is the more
> honest fix, because it does not depend on remembering an ordering rule under demo pressure.

> **Known drift, 2026-09-13 — the same failure a third time, closed for good this time.**
> `intervention_follow_through`, `candidate_preferences`, `day_disputes`
> (`202609060006_follow_through_loop.sql`) and seven newer tables
> (`202609060007_activity_catalogue.sql`, `202609060008_enjoyment_memory_goals_week_plan.sql`)
> reached the live project via `alembic upgrade head` with **RLS disabled and no policy at all**.
> Someone had concatenated the remaining unapplied mirrors into a local, never-committed
> `supabase_apply_all.sql` to close the gap in one step; that script inherited `202609060006`'s
> non-idempotent `create table`, rolled back on the first table it hit that Alembic had already
> created, and took the already-idempotent RLS statements for the newer tables down with it in
> the same transaction. `git ls-files | grep apply_all` has always been empty — the fix was never
> a real, reviewable artifact.
>
> Closed by [`infra/supabase/rls_posture_apply.sql`](../infra/supabase/rls_posture_apply.sql), a
> new, committed, RLS-only script — no `create table`, no `add column`, no `drop`, no data
> statement of any kind. It only enables RLS, clears `FORCE`, revokes `anon`/`authenticated` and
> installs `deny_browser_access`, guarded so it is safe to run any number of times regardless of
> what has or has not already been applied. That is a deliberately different shape from "make the
> historical mirrors idempotent," which was the honest fix proposed above and remains true going
> forward: `202609120011` onward already follow it. But `202608200001` through `202609060006` are
> not idempotent (bare `create table` / `create policy` with no guard), rewriting them changes
> files a live project already ran once with different content, and the actual, present harm —
> ten tables with no policy, right now — needs a fix that cannot itself be blocked by
> table-existence ordering. A schema-free script has no such failure mode by construction.
>
> [`infra/supabase/rls_posture_check.sql`](../infra/supabase/rls_posture_check.sql) is the
> read-only companion: one `select`, no side effects, reporting RLS-enabled / forced / policy
> names / `anon`+`authenticated` grants per table. Run it before and after applying the fix; see
> "Closing the RLS gap" below for the exact steps. `apps/api/tests/test_postgres_integration.py`
> replays `rls_posture_apply.sql` over an Alembic-built schema (twice) in CI and asserts the check
> query reports every ORM table green; `apps/api/tests/test_rls_posture_apply.py` is a
> database-free unit test asserting the script names every table `db_models.py` defines, so a
> future table added without RLS coverage fails locally, not just in CI.

`202609130012_dimension_preference_run_scope.sql` follows the idempotent pattern above from the
start: it adds one nullable `run_id` column, its foreign key and its index to
`activity_dimension_preferences`, each guarded the same way (`add column if not exists`, a
`pg_constraint` lookup, `create index if not exists`). It needs no RLS/deny policy of its own --
that table has carried both since `202609060007_activity_catalogue.sql`, and it alters no other
table. It backs ADR 0004 (`docs/adr/0004-run-scope-activity-dimension-preferences.md`): a demo
reset no longer deletes `activity_dimension_preferences` outright. A _standing_
`senior_statement` row (no `until`) keeps `run_id = null` and is never run-scoped, so it survives
a reset exactly like an outreach mute does. A _time-boxed_ `senior_statement` row (an `until`
day) and a `decline_reason`/`inferred` row are both stamped with the run that produced them and
go stale, but are not deleted, once that run is no longer active -- a time-boxed statement is a
promise about a day on that run's own calendar, and letting it outlive the run would let a reset,
which rewinds the calendar backward, read an already-lapsed promise as active again.

Every row this table already held before this revision also has `run_id = null`, purely because
the column did not exist yet -- not because any of them are standing beliefs. The file backfills
those rows in the same statement it mirrors from the Alembic migration: any row that is not a
standing statement (`source <> 'senior_statement'` or `expires_at is not null`) is stamped with
its person's currently active scenario run, guarded to touch only rows still `run_id is null` so
a second application is a no-op. A person with no active run at the time is left `null` rather
than guessed at; the read path (`_preference_inactive`) already treats a non-standing `null` row
as run-scoped and simply unmatched, so it reads as absent either way.

`202609150019_review_threshold_calibration.sql` (Alembic `485506d5a415`) follows the same idempotent
pattern. It creates the append-only `review_threshold_proposals` and `review_threshold_decisions`
tables with their update/delete triggers, RLS, revoked browser grants and deny policies, adds a nullable
`reached_too_late` column to `case_reviews`, and advances the Alembic marker from `d8b1e4f70c2a`.
Both tables are listed in `infra/supabase/rls_posture_apply.sql`. **It has not been applied to the live
project**; apply it by hand, then run the posture check. Design: ADR 0008.

`202609160020_review_context_gap.sql` (Alembic `7c3e9a1f4b28`) adds a nullable, not-backfilled
`case_reviews.context_gap_category varchar(40)` (`add column if not exists`). It needs no new policy or
trigger, because the existing RLS, deny policy and row-level append-only trigger on `case_reviews`
already cover a new column. **It has not been applied to the live project.** Apply it by hand, and
only **after** `202609150019`. Its `alembic_version` update moves the marker to `7c3e9a1f4b28` only
from exactly `485506d5a415`:

- Applied out of order, it adds the column but leaves the marker behind.
- Replayed after the API has already run `alembic upgrade head`, it changes nothing.

Afterwards, run the posture check and confirm `/ready` reports the repository head. Design: ADR 0009.

`202610140021_family_groups.sql` (Alembic `a4f6c2e81d37`) creates the five family-group tables
(`accounts`, `care_groups`, `group_members`, `family_pins`, `pin_attempts`) with `if not exists`,
enables RLS and adds the `deny_browser_access` policy on each (guarded, so a replay changes nothing).
All five are listed in `infra/supabase/rls_posture_apply.sql`. **It has not been applied to the live
project.** Apply it only **after** `202609160020`; it moves the marker to `a4f6c2e81d37` only from
exactly `7c3e9a1f4b28`.

`202610140022_family_calendar.sql` (Alembic `b9d3e5f71a26`) creates `appointments`,
`availability_entries` and `helper_assignments` the same way (`if not exists`, RLS on, guarded
`deny_browser_access` policies). All three are listed in `infra/supabase/rls_posture_apply.sql`.
**It has not been applied to the live project.** Apply it only **after** `202610140021`; it moves the
marker to `b9d3e5f71a26` only from exactly `a4f6c2e81d37`.

`202610240023_family_activity.sql` (Alembic `c4a7e1b93d58`) creates `family_activity`, the family
feed's append-only table, the same way (`if not exists`, RLS on, guarded `deny_browser_access`
policy). It is listed in `infra/supabase/rls_posture_apply.sql`. **It has not been applied to the live
project.** Apply it only **after** `202610140022`; it moves the marker to `c4a7e1b93d58` only from
exactly `b9d3e5f71a26`.

`202610240024_appointment_notes.sql` (Alembic `d8e2b6a4c917`) creates `appointment_notes`, the
family's per-day notes on appointments (deletable by their author, so not append-only), the same
way (`if not exists`, RLS on, guarded `deny_browser_access` policy). It is listed in
`infra/supabase/rls_posture_apply.sql`. **It has not been applied to the live project.** Apply it
only **after** `202610240023`; it moves the marker to `d8e2b6a4c917` only from exactly
`c4a7e1b93d58`.

`202610290025_unlinked_groups.sql` (Alembic `f3a9c1e7b254`) lets a family group exist before its
senior is linked (ADR 0010): it adds `care_groups.senior_name`, `linked_at` and `linked_by`
(`add column if not exists`), backfills them for existing groups from `people.display_name`,
`created_at` and `created_by`, sets `senior_name` not null and drops not null from `person_id`
(still unique) and `linked_via`. No new table, so no RLS change. Safe to run twice and over a
schema the API already upgraded. **It has not been applied to the live project.** Apply it only
**after** `202610240024`; it moves the marker to `f3a9c1e7b254` only from exactly `d8e2b6a4c917`.

`202610300026_group_member_last_opened.sql` (Alembic `c1e5a8f2d640`) adds the nullable
`group_members.last_opened_at` (`add column if not exists`); existing rows stay NULL. No new table,
so no RLS change. Safe to run twice and over a schema the API already upgraded. **It has not been
applied to the live project.** Apply it only **after** `202610290025`; it moves the marker to
`c1e5a8f2d640` only from exactly `f3a9c1e7b254`.

`202610300027_family_tasks.sql` (Alembic `a7d4c2e9f1b3`) creates `tasks` and `task_ticks`, the
family group's shared reminder list and the days ticked off, the same way (`if not exists`, RLS on,
guarded `deny_browser_access` policies). Both are listed in `infra/supabase/rls_posture_apply.sql`.
**It reached the live project on 2 Nov 2026 through API startup**: the lifespan ran `alembic upgrade
head` from `c1e5a8f2d640` and then `apply_rls_posture`, and `/ready` was checked afterwards. The
mirror file itself was not replayed there. It is idempotent, so replaying it now changes nothing.
On any other project, apply it only **after** `202610300026`; it moves the marker to `a7d4c2e9f1b3`
only from exactly `c1e5a8f2d640`.

`202611020028_helper_asks.sql` (Alembic `e6b2d9a4c718`) creates `helper_asks` (one member asking
another to take an appointment day) and `notifications` (the in-app notifications about asks), the
same way (`if not exists`, RLS on, guarded `deny_browser_access` policies), with the partial unique
index `uq_helper_asks_open_day` (`where state = 'open'`) that allows one open ask per appointment
day. Both are listed in `infra/supabase/rls_posture_apply.sql`. **It has not been applied to the
live project.** Apply it only **after** `202610300027`; it moves the marker to `e6b2d9a4c718` only
from exactly `a7d4c2e9f1b3`.

## Schema ownership

Three things can define this schema, and they have drifted from each other three times. The split is:

| Layer                                  | Owns                                                                                                                                                                                             | Must not own                                                                            |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Alembic (`apps/api/alembic/versions`)  | Tables, columns, indexes, constraints, triggers                                                                                                                                                  | Anything naming a Supabase platform role                                                |
| `infra/supabase/migrations/*.sql`      | RLS enablement, policies, grants and revokes                                                                                                                                                     | Table/column definitions that Alembic already owns                                      |
| `infra/supabase/rls_posture_apply.sql` | Re-establishing RLS enablement, policy and grants on every table in one idempotent step, independent of migration history. Run from the FastAPI lifespan on every start, and by hand when needed | Table/column definitions, and anything the migrations above have not already introduced |
| `infra/supabase/rls_posture_check.sql` | Read-only reporting of the posture the two rows above establish                                                                                                                                  | Any statement that changes the database                                                 |
| Supabase's migration tracker           | Nothing. It is a record, not a source of truth                                                                                                                                                   | —                                                                                       |

The hard rule: **an Alembic migration must never reference `anon`, `authenticated`, `service_role`
or any other Supabase platform role.** Those roles do not exist on stock PostgreSQL, and CI's
`postgres-integration` job runs against a plain `postgres:17` container — so such a migration fails
there with `role "anon" does not exist` while passing every local gate. This has already happened
once. `/ready` compares Alembic revisions and will catch a revision mismatch, but it cannot detect
a content mismatch between the two layers.

## The posture is established on every start, and reported by `/ready`

The procedure below is no longer the _only_ thing that establishes the posture, and should no
longer be the first thing that notices a gap.

`apps/api/src/silverloop/migrations.py::apply_rls_posture` runs
[`infra/supabase/rls_posture_apply.sql`](../infra/supabase/rls_posture_apply.sql) from the FastAPI
lifespan, immediately after `alembic upgrade head`, on every start. That order matters: the
posture has to cover the tables the upgrade just created, and on Supabase those arrive already
granted to `anon`/`authenticated` through `ALTER DEFAULT PRIVILEGES`. The window between "Alembic
created the table" and "a human pasted the script" — the window this file records losing three
times — is closed for existing databases as well as new ones, without touching a single applied
migration. The file is executed byte-for-byte through the raw driver cursor, so what runs at
startup is exactly what an operator would paste.

`/ready` then reports it. On PostgreSQL it lists every public ORM table whose
`pg_class.relrowsecurity` is false in `tables_without_rls`, and any name there makes `status`
`not_ready`. That is what makes _later_ drift visible: a `disable row level security` run in a SQL
console, a table created outside Alembic, or a failed apply. It is always empty off PostgreSQL —
SQLite has no such flag, and no Data API to be exposed to.

**An apply that fails is logged, not fatal.** The posture is a property of the database; crashing
the process would remove the surface that names the problem. The known cause is a **non-Supabase
PostgreSQL**: `anon` and `authenticated` do not exist on a stock server, so the script's `revoke`
aborts its own `do $$` block and the whole posture rolls back. On such a server `/ready` will
report every table in `tables_without_rls` and refuse to say `ready`. That report is literally
true — the deny posture is not established — and it is also harmless, because without those roles
there is no Data API to deny. If you run the shared profile against a plain PostgreSQL, create the
two roles (`create role anon nologin; create role authenticated nologin;`) so the posture the code
establishes is the posture you actually want, rather than relaxing the check.

## Closing the RLS gap (or confirming there isn't one)

This remains the human procedure, for a database the API has not started against, for confirming
the posture by hand, and for the grant and `rls_forced` checks `/ready` deliberately does not make.
Nothing here changes application schema or data; it only touches row-level security, grants and
policies, and the last step is read-only. `psql` and the Supabase SQL Editor both work — paste each
file's contents in order.

1. **Check first.** Run [`infra/supabase/rls_posture_check.sql`](../infra/supabase/rls_posture_check.sql)
   against the project. Save the output (a screenshot or a copy of the result grid is enough).
   Any row where `rls_enabled` is false, `rls_forced` is true, `policies` is not exactly
   `{deny_browser_access}`, or `anon_or_auth_grants` is not empty, is the gap.
2. **Apply.** Run [`infra/supabase/rls_posture_apply.sql`](../infra/supabase/rls_posture_apply.sql)
   against the same project. It is safe to run even if step 1 showed no gap, and safe to run
   twice if the connection drops partway through — every statement in it is idempotent by
   construction (see the file's own header comment for why).
3. **Check again.** Re-run `rls_posture_check.sql`. Every table must now read `rls_enabled = true`,
   `rls_forced = false`, `policies = {deny_browser_access}`, `anon_or_auth_grants = {}`. If any
   table still fails, stop and investigate rather than re-running the apply script — a script this
   simple failing to fix a table on the second pass means something unexpected is happening to
   that table outside this procedure, not that it needs a third try.
4. **Record it.** Note the date and the before/after check output somewhere durable (this file's
   changelog above, or the operator's own runbook) so the next person does not have to re-derive
   whether the gap is closed from the live database alone.

`apps/api/tests/test_postgres_integration.py` exercises exactly this apply-then-check sequence in
CI against a disposable database, so a regression in either file is caught before it reaches a
human running these steps against the shared project. It also exercises the startup path with no
mirror and no manual script at all — a bare `alembic upgrade head` followed by `apply_rls_posture`
— and asserts that opening one table by hand afterwards makes `/ready` name it.

## Backend connection

For a persistent FastAPI service, set `DATABASE_URL` to a server-side PostgreSQL connection using
the `psycopg` driver:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres?sslmode=require
```

Use the Supabase dashboard's current connection details rather than copying the illustrative value
above. Keep the database password in the deployment secret store and never expose it with a
`VITE_` prefix. For a long-running server, prefer the direct/session connection; use the
transaction pooler only where the hosting environment requires serverless connections.

On startup FastAPI runs `alembic upgrade head`, then `apply_rls_posture` (see above), then seeds a
deterministic scenario only when no active run exists. Start-up never touches the family data here:
the demo family is put back on start only with sign-in off on SQLite. The remote schema is currently marked at Alembic revision `c9d3e8f2a1b5`.

Standard `pnpm dev` and direct FastAPI lifespan startup reject SQLite when
`CAREPLUS_RUNTIME_PROFILE=shared`. The runtime also rejects the committed placeholder before it
attempts a connection. Use `pnpm demo:offline` when the deliberate SQLite fallback is required.

## Credential-safe smoke test

```bash
pnpm demo:supabase-smoke
```

The command requires the shared PostgreSQL profile, fixture mode and `LLM_ENABLED=false`. It runs
migrations, starts a new synthetic scenario, records one permitted outcome and verifies database
readiness and audit counters. Its output contains backend/revision/counter metadata but never the
connection string. Each run appends labelled synthetic evidence; do not point it at a production
database containing real participant data.

## Demo logins

The admin setup script creates the shared demo accounts in Supabase Auth:

```bash
cd apps/api
uv run --env-file ../../.env python -m silverloop.setup_demo_accounts
```

It needs `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `DATABASE_URL`, and the schema must already be
migrated. It refuses to run with `APP_ENV=production` unless `--allow-production` is passed. It asks
for each password at a hidden prompt, or reads `SENIOR_PASSWORD`-style variables (`SARAH_PASSWORD`,
`JOHN_PASSWORD`, `EMILY_PASSWORD`, `WEIMING_PASSWORD`, `AISHA_PASSWORD`, and so on) if they are set.
Leaving a prompt empty skips that account. Re-running updates the accounts and their passwords; it
never adds a second one.

| Username        | Account                |
| --------------- | ---------------------- |
| `senior`        | Mdm Lim, the senior    |
| `coordinator`   | Coordinator            |
| `demo-operator` | Demo operator          |
| `sarah`         | Family member Sarah    |
| `john`          | Family member John     |
| `emily`         | Family member Emily    |
| `weiming`       | Family member Wei Ming |
| `aisha`         | Family member Aisha    |

Supabase password sign-in needs an email, so each account has a hidden `@silverloop.demo` address.
The sign-in form adds that domain when the typed value has no `@`; real accounts keep signing in and
signing up with their own email.

The senior, coordinator and demo-operator accounts carry their role in Supabase `app_metadata`. The
family accounts are set up as a family member who signed up would be: no role in `app_metadata`,
and a row in `accounts` holding the role and display name. The script creates no family groups.

**Passwords are shared privately in the team's group chat, never in this repository, an issue or a
Claude session.** The script does not print them.

## Demo story

With sign-in on, the logins above belong to no family group. This command gives them the demo's
starting state, using synthetic data only:

```bash
pnpm demo:story
```

Nx loads the repository's `.env` into the command's environment, which is where `SUPABASE_URL`,
`SUPABASE_SECRET_KEY`, `DATABASE_URL` and `AUTH_ENABLED` come from. The same run without Nx is:

```bash
cd apps/api
uv run --env-file ../../.env python -m silverloop.demo_story
```

Run it on the morning of the demo and before each rehearsal, because the appointments are dated from
that day. It only reads Supabase Auth, and sets no password or role. It writes nothing and exits
non-zero if `APP_ENV=production`, if `AUTH_ENABLED=false`, if the database's Alembic revision is not
the repository's head (start the API once or run `alembic upgrade head`), or if any of `sarah`,
`john`, `emily`, `weiming`, `aisha` or `senior` is missing (run `setup_demo_accounts` first).

What it does, in order:

1. Starts a new run for Mdm Lim and plays two `activity_declines` days through the real `advance`,
   with the LLM off whatever the environment says. Day 1's nudge is answered "Maybe later"; day 2's
   programme suggestion stays waiting. The real ranking picks both, and the command prints their
   titles. A new run has active consent.
2. Puts Mdm Lim's family group back to its seeded schedule and feed, with Sarah (owner), John and
   Emily, and creates the unlinked group for the made-up Mr Tan with Sarah (owner), Wei Ming and
   Aisha. Sarah lands on Mdm Lim's group.
3. Reads the end state back and exits non-zero if it is wrong.

Re-running gives the same groups and the same shape of story, though the suggestion can differ (see
below).

**What a run deletes.** Inside the two demo groups, everything people added goes: other people's
memberships, their notes, their appointments and availability, and the feed rows. Other unlinked
groups created by the demo accounts go too, with everything in them. The group link's `linked_by`
moves to Sarah only if a seeded `demo-*` account made the link; a link someone really made keeps its
`linked_by`, `linked_via` and `linked_at`.

**What it leaves, and its limits.** Groups created by anyone else keep their members, appointments
and feed, and a demo login that joined one keeps its place there, because no route lets it leave. A
group a demo account created with a senior linked stays too, since only unlinked ones are removed. For
each of these the command prints a warning naming the login, the group's senior and the group's
creator, then carries on, so the login sees that group as well.
Two things do reach beyond the demo groups: creating Mr Tan's Join PIN clears every expired or used
Join PIN in the database, as any PIN creation does, and `reset` re-anchors the fixture activity
listings' times to the new run.

`POST /v1/demo/reset` with `AUTH_ENABLED=false` still puts the demo family back on PostgreSQL, which
removes real members from Mdm Lim's group. Only API start-up is limited to SQLite. Keep `AUTH_ENABLED=true`
whenever the API points at the team's shared Supabase.

The Mdm Lim steps commit one at a time and the group writes are one transaction, so a failure leaves
either a newer unfinished run for Mdm Lim with the groups unchanged, or no group change at all.
Running it again repairs both.

**Why the suggestion can differ.** Reset keeps what Mdm Lim said. Her earlier "Yes, I'd like that"
and "Not for me" answers keep shaping the ranking, because outcomes are append-only, and a suggestion
left unanswered closes as `no_response` once its reply window passes, which counts too. "Maybe later"
is recorded but moves the ranking by nothing, so it does not change the next run's suggestion. Three
"Not for me" answers to one suggestion mute it automatically. In each case the command
succeeds with the next-ranked suggestion and prints its title. If she has muted every nudge, day 1
offers none and the command says so.

**When it cannot finish.** If the policy decides anything else on either day, the command exits
non-zero and names the decision, for example when every programme suggestion is muted. Running it
again decides the same thing until that changes. Lift a mute with
`POST /v1/people/mdm-lim/preferences/{candidate_key}` signed in as `senior`. The command cannot remove
an earlier answer.

The Join PIN in Mr Tan's group lasts 7 days. Any active member gets a fresh one from the group's
Family page (`POST /v1/groups/{id}/join-pin`). The command does not print the PIN.

## Operational checks

After applying any later migration:

1. Run [`infra/supabase/rls_posture_check.sql`](../infra/supabase/rls_posture_check.sql) and
   confirm every table still reads RLS enabled, not forced, exactly one `deny_browser_access`
   policy and no `anon`/`authenticated` grants (see "Closing the RLS gap" above).
2. Run Supabase security and performance advisors.
3. Confirm the Alembic revision matches the repository.
4. Run the API scenario suite against SQLite and `pnpm test:postgres` against a disposable database
   whose name contains `test`.
5. Call `/ready` and confirm the connected and expected Alembic revisions match and that
   `tables_without_rls` is empty.

Unused-index notices are expected while the database is empty; reassess them only after realistic
query traffic exists. Do not remove evidence or foreign-key indexes solely to silence an empty
database advisory.
