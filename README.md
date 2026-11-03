# Care+

Care+ is an agentic active-ageing and AAC outreach prototype. It learns personal activity
baselines, validates data quality, considers context, chooses the least intrusive permitted action,
observes outcomes, and adapts future intervention choices. It is not a medical or emergency system.

## Repository status

The core demo is synthetic and offline-capable; Healthy 365 and real AAC integrations are future,
authorised adapters only.

## Prerequisites

- Node.js 24
- pnpm 11
- Python 3.13
- uv

Supabase PostgreSQL is the default shared runtime. Docker is optional; SQLite remains available for
tests and the explicit emergency offline demo.

## Quick start (no accounts or credentials)

You need Node 24, pnpm 11, and Python 3.13 with [uv](https://docs.astral.sh/uv/).

```bash
pnpm --dir client install
cd server && uv sync && cd ..
pnpm demo:offline
```

`client/` (the web app), `e2e/` (the Playwright suite) and `server/` (the API) are separate installs
with their own lockfiles; the root `package.json` has no dependencies and only runs scripts, so
every `pnpm …` command below works from the repo root. `pnpm run setup` installs all three.

`pnpm demo:offline` starts the API on a local SQLite file with synthetic data and no language
model, and the web app with sign-in off. It works in any shell, including Windows. Open:

- Web: <http://127.0.0.1:3000>
- API docs: <http://127.0.0.1:8000/docs>

**No username or password is needed for this mode** -- sign-in is disabled, so every screen is
reachable directly. Only the Supabase-backed "Shared runtime" below uses real accounts, created
through Supabase's own sign-up, not a fixed demo login.

The web app is a Vue 3 + Bootstrap 5 single-page app in `client`. The family screens use a
bottom tab bar on phones and a header pill on desktop. **Home** is a daily overview (the senior's
activity against a usual day, a feed of what the family has done, a one-tap "Tell the family you
were in touch" check-in, a brief look at the calendar, and today's tasks and medicine). **Senior**
(the senior's own day: activity, one suggestion to answer with large buttons, and today's plans)
follows the loop from there. **Calendar** (Mdm Lim's activities and appointments and who is
helping; on phones a week strip, the day's agenda and a bottom sheet with each day's family notes,
kept apart from the appointment's own details; on desktop the month grid) and **Family** (the care
group, an invite PIN, and when each member can help) help a family share the care. Calendar and family
coordination use the API, and so do tasks on Home and Senior (one-off, daily or weekly, kept by the
family group), which show on the calendar too; see `docs/tasks.md`.
Only the offline demo persona, Mdm Lim, exists until you run `pnpm seed`.

## Shared runtime (Supabase)

```bash
pnpm run setup
# Replace the placeholder DATABASE_URL in .env with a server-side Supabase connection string.
pnpm dev
```

## Main commands

```bash
pnpm dev
pnpm demo:offline
pnpm test
pnpm test:postgres
pnpm lint
pnpm typecheck
pnpm demo:reset
pnpm demo:smoke
pnpm demo:supabase-smoke
```

## Testing

```bash
pnpm test            # Python unit/API tests, plus the Playwright browser suite
pnpm test:e2e         # just the Playwright browser suite (e2e/tests)
pnpm test:scenarios   # YAML safety-policy scenarios under scenarios/
pnpm test:postgres    # needs SILVERLOOP_POSTGRES_TEST_URL; the database name must contain "test"
pnpm verify           # format, contract, lint, typecheck, test, scenarios, build -- what CI runs
```

`pnpm test:e2e` (and `pnpm test`) start their own API and web servers against a throwaway SQLite
database, so nothing needs to be running first. See [`docs/testing.md`](./docs/testing.md) for what
each layer of tests actually establishes.

The outreach planning agent, its deterministic guardrail and the bounded plan/act/adapt loop are
described in [`agenticlayer.md`](./agenticlayer.md). It is off by default; the complete demo runs
with `LLM_ENABLED=false`.

The API also carries features that no current screen uses (coordinator review tools, activity
search, week plans and preferences). They are reachable from the API docs at `/docs`; see
[`docs/architecture.md`](./docs/architecture.md).

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for team workflow and
[`docs/architecture.md`](./docs/architecture.md) for system boundaries.

Wearable inputs are detachable and provider-neutral; see
[`docs/data-adapters.md`](./docs/data-adapters.md) for the synthetic default, consented sample
normalisation and the explicit Healthy 365 future-only boundary.

For a clean-machine walkthrough use [`docs/setup.md`](./docs/setup.md). For the three-minute demo
and what to do if something goes wrong, use [`docs/demo-script.md`](./docs/demo-script.md).

## Data truth

The default demo uses reproducible synthetic daily metrics, cached context fixtures, mock AAC
programmes and simulated outcomes. Team-owned Apple/Garmin exports are optional, consented proofs
of adapter normalisation only. Synthetic results validate software policy, not clinical outcomes.

## Licence

Copyright remains with the project team. Add an explicit open-source licence only after the team
agrees on one.
