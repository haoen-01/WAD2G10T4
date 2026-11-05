# Care+

Care+ helps a family look after an older relative who lives on their own. A simulated smartwatch
tracks the senior's daily activity. Care+ learns what a usual day looks like for them, checks that
each day's readings can be trusted, and then picks the gentlest helpful step: nothing at all, a
friendly nudge, a suggestion for a community programme, or flagging the day for a person to look
at. The family shares a calendar, tasks and updates around the senior.

Care+ is a wellness and coordination app. It does not diagnose, predict illness, detect falls,
give medication advice, call emergency services or contact anyone without the senior's consent,
and it never treats heart rate or blood-oxygen readings as a medical signal. All activity data in
this repository is synthetic.

## Features

| Screen       | Who    | What it does                                                                                                                                                 |
| ------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Home**     | Family | Today's activity against the senior's usual day, today's tasks, a feed of what the family has done, a one-tap check-in and the week ahead.                   |
| **Senior**   | Senior | A calm view of their own day with large buttons: one suggestion to answer, today's tasks to tick off, plans for the day and an optional read-aloud summary.  |
| **Calendar** | Family | Shared appointments and activities, who is helping with each, availability and per-day family notes. Week strip and agenda on phones, month grid on desktop. |
| **Family**   | Family | The care group, an invite PIN, members and when each can help.                                                                                               |
| **Walk**     | Family | A 3D map of the senior's walk while they choose to share it, with a replay of today's walk.                                                                  |
| **Watch**    | Senior | The simulated watch in 3D and its status (battery, wear time, last sync).                                                                                    |
| **Badges**   | Both   | Step and walking milestones the senior can earn and claim.                                                                                                   |
| **Kaki**     | Both   | A read-only helper that answers questions about the day. Emergency, medicine and symptom questions always get a fixed safety reply.                          |

Display-only public data is shown where it helps: the data.gov.sg two-hour weather forecast and
Singapore public holidays (Nager.Date). No key is used and nothing about the senior is sent, and
the app keeps working when these services are unavailable.

## How the daily decision works

Each simulated day the API runs one step:

1. **Baseline.** The senior's usual activity is the median of recent days, with a robust spread
   (median absolute deviation), so one unusual day does not move it much.
2. **Data quality.** A day with less than 8 hours of watch wear is not trusted.
3. **Policy.** A fixed, rule-based ladder decides what is allowed. Gates are checked in order:
   consent, data quality, confidence, rain, how large and lasting the change is, and a cap on how
   often the senior is contacted. The result is one of `suppress`, `no_action`, `gentle_nudge`,
   `programme_suggestion` or `coordinator_review`. "No action" is recorded like any other result.
4. **Ranking.** Among the options the policy allows, a small learner (Beta-Bernoulli) ranks them by
   how the senior has responded before. It can reorder permitted options but never override a
   gate.
5. **Optional AI planner.** With `LLM_ENABLED=true` and a key, an AI planner may reorder or reword
   the permitted suggestions; a deterministic guardrail checks every proposal. It is off by
   default, and the whole app works without it.
6. **Audit.** Every decision is stored with its evidence: source, timestamp, confidence and an
   evidence ID.

## Tech stack

- **Web app (`client/`):** Vue 3, Vite, TypeScript, Bootstrap 5, Pinia, Axios, motion-v.
- **API (`server/`):** Python 3.13, FastAPI, Pydantic, SQLAlchemy 2, Alembic, managed with uv.
- **Database:** Supabase PostgreSQL for the shared app; SQLite for tests and the offline demo.
- **Sign-in:** Supabase Auth (the browser uses Supabase only to sign in; all data goes through the
  API).
- **Tests:** Playwright (browser), pytest (API), Node's test runner and Vitest (web logic).
- **Hosting:** Vercel (one project for `client/`, one for `server/`).

The API's request and response models are the single contract: they produce
`openapi/silverloop.json`, from which the web app's TypeScript client in
`client/src/api-client/generated` is generated.

## Repository layout

```
client/          Vue web app
server/          FastAPI app, database models, Alembic migrations and API tests
e2e/             Playwright browser tests
openapi/         The committed OpenAPI contract
infra/supabase/  SQL migrations mirroring Alembic, plus row-level-security deny policies
scenarios/       YAML scenarios that pin the decision policy's behaviour
scripts/         Dev, test, contract and demo scripts behind the root package.json
tools/           Synthetic data generator
docs/            Architecture, API, testing, setup, Supabase and design notes
```

## Getting started

You need Node.js 24, pnpm 11, Python 3.13 and [uv](https://docs.astral.sh/uv/).

### Offline demo (no accounts needed)

```bash
pnpm run setup
pnpm demo:offline
```

This starts the API on a local SQLite file with synthetic data, no AI and sign-in turned off,
plus the web app. Open <http://127.0.0.1:3000> for the app and <http://127.0.0.1:8000/docs> for the
API docs. No username or password is needed.

### With Supabase

```bash
pnpm run setup
# In .env, set DATABASE_URL to your Supabase session pooler connection string (port 5432)
pnpm dev
```

`pnpm demo:story` puts the shared Supabase demo into its starting state. See
[`docs/supabase.md`](./docs/supabase.md) for accounts, sign-in and row-level security.

`client/`, `server/` and `e2e/` each have their own install and lockfile. The root `package.json`
has no dependencies; it only runs scripts, so every `pnpm …` command works from the repository
root.

## Testing

```bash
pnpm test             # API tests, then the Playwright browser suite
pnpm test:e2e         # only the Playwright browser suite (e2e/tests)
pnpm test:scenarios   # the decision-policy scenarios in scenarios/
pnpm verify           # format, contract, lint, typecheck, tests, scenarios and build (what CI runs)
```

The browser suite starts its own API and web app on a throwaway SQLite database with fixed demo
dates, so nothing needs to be running first and every run starts from the same state. Web logic
tests run with `pnpm --dir client test`. See [`docs/testing.md`](./docs/testing.md) for what each
layer covers.

GitHub Actions runs `pnpm verify` and a PostgreSQL integration job on every pull request.

### End-to-end tests

The Playwright end-to-end tests are in `e2e/tests`. The core user journeys (signing in as each
role, shared tasks, the calendar, the daily suggestion loop and the Kaki assistant, each with a
success path and a failure or safety path) are in `e2e/tests/core`.

To run them on a fresh clone:

```bash
pnpm run setup                                   # installs everything, including the test browser
pnpm test:e2e                                    # the whole browser suite
cd e2e && pnpm exec playwright test tests/core   # only the core journeys
```

No accounts, keys or running servers are needed. Each run starts its own API and web app on a
throwaway SQLite database with fixed demo dates, and every test resets the demo data first, so the
results are the same on any day and in any order. Stop `pnpm dev` or `pnpm demo:offline` first,
as the tests use the same ports (8000 and 3000). Add `--reporter=html`, then run
`pnpm exec playwright show-report` from `e2e/`, for the HTML report.

## Deployment

Both apps deploy to Vercel from `main`.

- **Server project** (root `server/`): `DATABASE_URL` (Supabase session pooler, port 5432),
  `APP_ENV=demo`, `LLM_ENABLED=false`, `CORS_ORIGINS` set to the client's URL,
  `DATABASE_POOL_SIZE=1` and `DATABASE_MAX_OVERFLOW=1`. Add `AUTH_ENABLED=true` with
  `SUPABASE_URL` for real sign-in.
- **Client project** (root `client/`): `VITE_API_BASE_URL` set to the server's URL, plus
  `VITE_AUTH_ENABLED`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` for sign-in. These
  are read at build time, so redeploy after changing them.

After deploying, `GET /ready` on the server should report `"ready": true`. If it lists
`tables_without_rls`, run `infra/supabase/rls_posture_apply.sql` once in the Supabase SQL editor.

All settings are described in [`.env.example`](./.env.example). Never commit a real `.env`.

## More documentation

- [`docs/setup.md`](./docs/setup.md): setting up on a clean machine
- [`docs/architecture.md`](./docs/architecture.md): how the parts fit together
- [`docs/api.md`](./docs/api.md): the API routes
- [`docs/testing.md`](./docs/testing.md): the test layers
- [`docs/demo-script.md`](./docs/demo-script.md): a walkthrough of the demo
- [`docs/agentic-layer.md`](./docs/agentic-layer.md): the optional AI planner and its guardrail
- [`docs/principles.md`](./docs/principles.md): the product boundary and engineering rules
- [`docs/glossary.md`](./docs/glossary.md): the terms used across the app and docs
- [`CONTRIBUTING.md`](./CONTRIBUTING.md): branches, commits and pull requests
- [`SECURITY.md`](./SECURITY.md): security practices and reporting

## AI declaration

AI/LLM tools were used to assist with project ideation, brainstorming, UI/UX design inspiration,
and providing coding guidance, including explanations of technical concepts and debugging
suggestions.

## Licence

Copyright remains with the project team. No open-source licence has been chosen.
