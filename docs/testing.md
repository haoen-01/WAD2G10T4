# Testing

## Gates

`pnpm verify` (`scripts/verify.sh`) runs, in order: `format:check`, `client:check` (the generated
contract is current), `lint` (ruff), `typecheck` (`vue-tsc` and `tsc` for the client and e2e,
`compileall` for the server and the synthetic-data tool), `test`, `test:scenarios` and `build`.

`pnpm test` (`scripts/test.mjs`) runs three suites one after another, each even if an earlier one
failed, and exits non-zero if any did:

1. the server suite (`uv run pytest` in `server/`);
2. the client unit tests (`pnpm --dir client test`);
3. the Playwright suite (`pnpm --dir e2e test`).

They run in sequence on purpose: run at the same time, the CPU-bound server suite starves the
browser suite's dev servers on a small machine and the e2e tests fail on timing rather than on
behaviour.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`, with two jobs:

- **`verify`** (30-minute timeout) installs `client/`, `e2e/` and `server/` from their lockfiles and
  pinned Chromium, then runs the same gates as `pnpm verify` one by one. When the job fails or is
  cancelled it uploads `e2e/test-results` and `e2e/playwright-report` as `playwright-results`.
- **`postgres-integration`** (10-minute timeout) starts a disposable `postgres:17` service with a
  database named `silverloop_test`, sets `SILVERLOOP_POSTGRES_TEST_URL` and runs
  `pnpm test:postgres`.

## Server tests (`server/tests/`)

Pytest over the API, the repository and the domain modules, on in-memory or temporary SQLite with
fixture adapters and the LLM off. `conftest.py` sets `DEMO_DATES_FOLLOW_TODAY=false`, so the
readings stay on the fixture's anchor day (Tue 18 Aug 2026); `test_demo_dates.py` covers moving
them to today. A few groups worth knowing:

- **Decision loop and safety:** `test_policy.py`, `test_quality.py`, `test_analytics.py`,
  `test_consent_boundary.py`, `test_simulation_events.py` (event IDs are idempotent and cannot be
  reused for another event), `test_response_clock.py` (an unanswered suggestion closes as
  `no_response` after its reply window), `test_learning_weights.py` (a reported completion
  outweighs a bare tap, and every outcome kind has a weight), `test_follow_up.py` (every
  follow-up observation carries its non-causal caveat).
- **Family features:** `test_family_groups.py`, `test_family_calendar.py`,
  `test_family_activity.py`, `test_appointment_notes.py`, `test_family_tasks.py`,
  `test_family_asks.py`, `test_family_unlinked_groups.py`, `test_wearable_status.py`,
  `test_senior_day.py`, and the family agents (`test_catchup_agent.py`,
  `test_appointment_draft_agent.py`, `test_my_day_agent.py`).
- **Kaki and voice:** `test_assistant.py`, `test_tts.py`.
- **Auth:** `test_auth_jwt.py`, `test_auth_rbac.py`, `test_auth_resources.py`.
- **Outreach planner:** `test_agent_planner.py`, `test_agent_integration.py`,
  `test_prompt_injection.py` (person text and catalogue titles reach a prompt fenced as data and
  cannot widen the allow-list), and `test_recorded_client.py`, which covers the `recorded` provider
  with small synthetic recordings it writes to a temporary directory; none are committed.
- **Database and posture:** `test_query_counts.py` pins how many SQL statements each person read
  issues (each is a round trip to the pooler on the shared database) and that the count does not
  grow with history; raising a ceiling needs review. `test_engine_options.py` covers the pool
  settings without connecting. `test_supabase_mirror.py` checks every ORM table has a deny policy
  in a mirror file and the newest mirror advances `alembic_version` to the head;
  `test_rls_posture_apply.py` checks `rls_posture_apply.sql` names every table in `db_models.py`;
  `test_rls_posture_startup.py` covers the start-up apply and `/ready`.
- **Error handling:** `test_error_handling.py`, `test_failure_paths.py`,
  `test_stored_state_compat.py` (a snapshot from an older contract returns a classified
  `stored_state_incompatible` 500 and recovers on reset).
- **Demo tooling:** `test_demo_story.py`, `test_setup_demo_accounts.py`, `test_runtime.py`.

Some backend features have no screen but still run inside `advance` (the review setting's daily
checks, replan offers, system-closed review cases, mutes and day disputes). Their tests stay; state
that no route writes any more is created as rows through `tests/row_fixtures.py`.

## Client tests (`client/`)

`pnpm --dir client test` runs two things:

- `node --test` over `src/lib/*.test.ts`: the pure logic behind the screens (calendar, coverage,
  family feed, tasks, asks, badges, walk, watch, day timeline, Read my day, Kaki's chat, morning
  summary, holidays, weather, ICS export, PIN countdowns, sign-in email, route guard and more).
  Keep state changes in pure `lib/` functions so they can be tested here.
- Vitest over `src/stores/*.spec.ts` (the Pinia stores: `activity`, `calendar`, `session`,
  `reset`), using the app's own Vite config so the `@/` alias and `import.meta.env` work; each
  test gets its own Pinia. `pnpm --dir client test:stores` runs these alone.

## Browser tests (`e2e/`)

`pnpm test:e2e` runs Playwright. `e2e/playwright.config.ts` starts its own API and Vite dev server
(`reuseExistingServer: false`), so it never touches a running `pnpm dev` or Supabase:

- the API under the `offline` profile on a temporary SQLite file, with fixture adapters,
  `LLM_ENABLED=false`, `TTS_ENABLED=false`, `AUTH_ENABLED=false` and
  `DEMO_DATES_FOLLOW_TODAY=false`, so the readings keep the anchor day the specs assert against;
- Vite with sign-in off and the walk map on its offline sketch;
- browser and test code on `Asia/Singapore` time, one worker, one retry in CI, with the morning
  summary switched off in every spec except `morning-summary.spec.ts`.

`E2E_API_PORT` and `E2E_WEB_PORT` move the ports (defaults 8000 and 3000) so the suite can run
beside `pnpm dev`. Each spec file covers one area, for example `loop.spec.ts` (watch status, a
simulated decline reaching the senior, consent withdrawn through the API), `groups.spec.ts`,
`family.spec.ts`, `tasks.spec.ts`, `asks.spec.ts`, `home-feed.spec.ts`, `calendar-sheet.spec.ts`,
`badges.spec.ts`, `walk.spec.ts`, `watch.spec.ts`, `assistant.spec.ts`, `read-my-day.spec.ts`,
`day-timeline.spec.ts`, `public-apis.spec.ts` (Home and the calendar still work when the forecast
or holidays cannot be reached) and the layout specs (`responsive`, `shared-look`, `sign-in-look`,
`senior-polish`, `ui-revamp`).

## Scenarios

`pnpm test:scenarios` runs every `scenarios/*.yaml` through the real repository. Each file lists
events and `expected_decisions`, optionally `expected_cases` and `expected_outcomes` (one entry per
intervention, oldest first, `null` for one still open). The scenarios never follow today's date.
`scenarios/holdout/` is a separate set that the command does not reach; `test_scenarios.py` runs it
inside the server suite and checks it stays separate.

## PostgreSQL integration

```bash
SILVERLOOP_POSTGRES_TEST_URL=postgresql+psycopg://... pnpm test:postgres
```

`server/tests/test_postgres_integration.py` (marked `postgres`) refuses any URL whose database name
does not contain `test`, so it cannot target the normal Supabase `postgres` database. It applies the
Alembic head, checks idempotent state across a repository restart, consent withdrawal and the
append-only triggers, runs the demo story twice, and replays the Supabase mirror and
`rls_posture_apply.sql` over an Alembic-built schema, asserting the check query reports every table
denied to the browser.

## What the tests do not establish

- Clinical validity, fall detection or improved health outcomes.
- Healthy 365 access or any real community-programme availability.
- Fairness across groups, from synthetic data.
- Production security, durability or suitability for emergencies.
- That a suggestion causes activity to change; follow-up observations are descriptive.
- That the learning weights or the three-declines mute are well calibrated: the tests fix the
  ordering the product depends on, not the numbers.

Checks that need a person are in [`manual-ui-checklist.md`](manual-ui-checklist.md).
