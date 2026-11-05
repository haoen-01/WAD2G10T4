# Supabase

Care+ uses Supabase for two things: managed PostgreSQL for the shared runtime, and Supabase Auth for
sign-in. It is not a second backend. FastAPI owns every domain read and write; the browser uses
Supabase JS for sign-in and the session only and never touches the tables, which deny the `anon`
and `authenticated` roles. SQLite is used only by the tests and `pnpm demo:offline`.

## Project setup

1. Create a Supabase project (keep separate development and demo projects where the account allows).
2. **Database URL.** In the dashboard, **Connect** → **Session pooler**. Use that URL with the
   `psycopg` driver and keep port **5432**; the username includes the project reference:

   ```dotenv
   DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres?sslmode=require
   ```

   The session pooler works on IPv4-only networks. Keep the pool within its client cap; the
   defaults in `.env.example` (`DATABASE_POOL_SIZE=10`, `DATABASE_MAX_OVERFLOW=4`) stay under 15.

3. **API keys.** `SUPABASE_URL` is the project URL. `SUPABASE_SECRET_KEY` is needed only by
   `setup_demo_accounts` and `demo_story`. The client gets `VITE_SUPABASE_URL` and the
   **publishable** key as `VITE_SUPABASE_PUBLISHABLE_KEY`, never a secret key.
4. Put the real values in the local `.env` or the deployment's environment variables. Never commit
   them, and never put the database password or secret key in a `VITE_` variable.

`pnpm dev` and the API lifespan refuse SQLite under `CAREPLUS_RUNTIME_PROFILE=shared`, and refuse
the committed placeholder `DATABASE_URL` before trying to connect. Use `pnpm demo:offline` when you
want SQLite.

## Auth settings

- **Email provider with passwords.** The client signs in with `signInWithPassword` and signs up with
  `signUp`. If **Confirm email** is on, a new account sees "Check your email" and signs in after
  confirming; set the project's **Site URL** to the client's origin so the link lands on Care+.
- **Token verification.** The API verifies Supabase access tokens (audience `authenticated`)
  against the project's JWKS at `SUPABASE_URL/auth/v1/.well-known/jwks.json` (ES256 or RS256).
  `SUPABASE_JWT_SECRET` is only for a project still on legacy HS256 keys.
- Roles live in the API, not in Supabase: a person who signs up chooses senior or family in
  `/v1/me/onboard`, stored in the `accounts` table. Only the senior, coordinator and demo-operator
  demo accounts carry a role in `app_metadata`.
- Keep `AUTH_ENABLED=true` and `VITE_AUTH_ENABLED=true` whenever the API points at the shared
  project.

## Migrations

- **Alembic owns the schema** (`server/alembic/versions`). On every start the API lifespan runs
  `alembic upgrade head`, then applies the RLS posture (below), then seeds a scenario only when no
  active run exists. `pnpm migrate` runs the upgrade by hand. Do not edit the schema in Supabase
  Studio.
- **`infra/supabase/migrations/*.sql`** is the hand-applied mirror of each Alembic revision's
  RLS posture: row-level security enabled, `anon`/`authenticated` revoked and a
  `deny_browser_access` policy on every table, plus append-only triggers on decision, consent,
  outcome, review and audit evidence. Each file advances `alembic_version` only from the revision
  before it, so apply them in filename order. The newer files are idempotent (`if not exists`,
  guarded policies), so they can be replayed over a schema the API already upgraded. Do not
  rewrite a file that has been applied to a live project.
- **Never reference a Supabase role in an Alembic migration.** `anon`, `authenticated` and
  `service_role` do not exist on stock PostgreSQL, so such a migration fails in CI's
  `postgres-integration` job. Roles, grants and policies belong in the mirror and in
  `rls_posture_apply.sql`.

`server/tests/test_supabase_mirror.py` checks that every ORM table has a deny policy in some mirror
file and that the newest mirror advances `alembic_version` to the repository head, so a new table
cannot land without its mirror.

## Row-level security

`server/src/silverloop/migrations.py::apply_rls_posture` runs
[`infra/supabase/rls_posture_apply.sql`](../infra/supabase/rls_posture_apply.sql) straight after
`alembic upgrade head` on every start. The script is idempotent and changes no schema or data: for
every table the ORM defines it enables RLS, clears `FORCE`, revokes `anon`/`authenticated` and
installs `deny_browser_access`. This matters because Supabase grants new tables in `public` to
those roles by default.

`GET /ready` reports the result. On PostgreSQL it lists every ORM table with RLS off in
`tables_without_rls`, and any name there (or an Alembic revision that is not the repository head)
makes `status` `not_ready`. A failed apply is logged, not fatal, so `/ready` can name the problem.

**A Vercel deploy of `server/` alone does not ship `infra/`.** The API then starts without the file,
logs `rls_posture_apply_missing` and applies nothing. After each deploy that adds a table, call
`GET /ready`; if `tables_without_rls` is not empty, apply the posture by hand:

1. Run [`infra/supabase/rls_posture_check.sql`](../infra/supabase/rls_posture_check.sql) (read-only)
   in the Supabase SQL Editor or `psql`. Any row with `rls_enabled` false, `rls_forced` true,
   `policies` other than `{deny_browser_access}`, or a non-empty `anon_or_auth_grants` is a gap.
2. Run `rls_posture_apply.sql`. It is safe to run any number of times.
3. Run the check again and confirm every table is green, then confirm `/ready` reports
   `tables_without_rls: []`. If a table still fails after a second pass, investigate rather than
   re-running.

On a non-Supabase PostgreSQL the roles do not exist, the script's `revoke` fails and `/ready` lists
every table. Create the two roles (`create role anon nologin; create role authenticated nologin;`)
rather than relaxing the check. `server/tests/test_postgres_integration.py` replays the apply and
check scripts over an Alembic-built schema in CI.

## Credential-safe smoke test

```bash
pnpm demo:supabase-smoke
```

Requires the shared profile, `ADAPTER_MODE=fixture` and `LLM_ENABLED=false`. It runs migrations,
starts a new synthetic scenario, records one permitted outcome and checks readiness and audit
counters. Its output never contains the connection string. Each run adds labelled synthetic
evidence, so never point it at a database holding real data. Run it with the same
`DEMO_DATES_FOLLOW_TODAY` value as the API (its reset moves the sample programmes too), and run
`pnpm demo:story` afterwards to put the signed-in demo back.

## Demo accounts

```bash
cd server
uv run --env-file ../.env python -m silverloop.setup_demo_accounts
```

Needs `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `DATABASE_URL`, and a migrated schema. It refuses
`APP_ENV=production` unless `--allow-production` is passed. It asks for each password at a hidden
prompt, or reads `SENIOR_PASSWORD`, `COORDINATOR_PASSWORD`, `DEMO_OPERATOR_PASSWORD`,
`SARAH_PASSWORD`, `JOHN_PASSWORD`, `EMILY_PASSWORD`, `WEIMING_PASSWORD` and `AISHA_PASSWORD` if set.
An empty prompt skips that account. Re-running updates accounts and passwords; it never creates a
duplicate.

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

Each account has a hidden `@silverloop.demo` email; the sign-in form adds that domain when the typed
value has no `@`. Real accounts sign in with their own email. The family accounts have no role in
`app_metadata` and a row in `accounts`, like anyone who signed up. The script creates no family
groups.

**Passwords are never in this repository or an issue.** They are shared privately within the team,
and the script does not print them.

## Demo story

With sign-in on, the demo logins start in no family group. This gives them the demo's starting
state, using synthetic data only:

```bash
pnpm demo:story
```

The root script loads `.env` (`scripts/run.mjs`). By hand, from `server/`:

```bash
uv run --env-file ../.env python -m silverloop.demo_story
```

Run it on the morning of the demo and before each rehearsal, because appointments are dated from
that day. It reads Supabase Auth only and sets no password or role. It changes nothing and exits
non-zero if `APP_ENV=production`, if `AUTH_ENABLED=false`, if the database is not at the repository's
Alembic head (start the API once or run `pnpm migrate`), or if `sarah`, `john`, `emily`, `weiming`,
`aisha` or `senior` is missing (run `setup_demo_accounts` first).

What it does:

1. Starts a new run for Mdm Lim and plays two `activity_declines` days through the real `advance`,
   with the LLM off. Day 1's nudge is answered "Maybe later"; day 2's community programme suggestion
   stays waiting. The command prints both titles. With `DEMO_DATES_FOLLOW_TODAY=true` (the default)
   her second day is today in Singapore; with it false the run keeps the fixture's days in August 2026.
2. Puts Mdm Lim's family group back to its seeded schedule and feed, with Sarah (owner), John and
   Emily, and creates an unlinked group for the made-up Mr Tan with Sarah (owner), Wei Ming and
   Aisha. Sarah lands on Mdm Lim's group.
3. Reads the end state back and exits non-zero if it is wrong.

**What a run deletes.** Inside the two demo groups: other people's memberships, notes,
appointments, availability and feed rows. Other unlinked groups created by the demo accounts go too.
A group link's `linked_by` moves to Sarah only if a seeded `demo-*` account made it.

**What it leaves.** Groups created by anyone else, and a demo login's place in them, stay; so does a
group a demo account created with a senior linked. The command prints a warning naming each. It also
clears expired or used Join PINs across the database (as any PIN creation does) and re-anchors the
fixture activity listings to the new run.

`POST /v1/demo/reset` with `AUTH_ENABLED=false` puts the demo family back on PostgreSQL too, which
removes real members from Mdm Lim's group, so keep `AUTH_ENABLED=true` against the shared project.

The Mdm Lim steps commit one at a time and the group writes are one transaction, so a failure leaves
either a newer unfinished run with the groups unchanged, or no group change at all. Running it again
repairs both.

**Why the suggestion can differ.** Reset keeps what Mdm Lim said. "Yes, I'd like that", "Not for
me" and suggestions closed as `no_response` keep shaping the ranking; "Maybe later" moves nothing.
Three "Not for me" answers to one suggestion mute it. The command succeeds with the next-ranked
suggestion and prints its title. If the policy decides anything else on either day (for example,
every programme suggestion is muted), it exits non-zero and names the decision. No route lifts a
mute, so that state persists until the mute rows are removed from the database.

Mr Tan's Join PIN lasts 7 days. Any active member gets a fresh one from the group's Family page
(`POST /v1/groups/{id}/join-pin`). The command does not print it.

## After a schema change

1. Confirm `/ready` reports matching connected and expected Alembic revisions and an empty
   `tables_without_rls`.
2. Run `rls_posture_check.sql` and confirm every table is green.
3. Run the Supabase security and performance advisors. Unused-index notices are expected while the
   database is nearly empty; do not drop evidence or foreign-key indexes to silence them.
4. Run `pnpm test:scenarios` and `pnpm test:postgres` against a disposable database whose name
   contains `test`.
