# CLAUDE.md

Guidance for Claude Code when working in this repository.

# Engineering workflow

The main Claude conversation acts as the engineering lead and orchestrator.

For non-trivial features, do not immediately start coding.

## Required workflow

### 1. Understand

Establish:

- requested outcome
- constraints
- relevant existing behavior
- acceptance criteria

Do not expand scope beyond the user's request.

### 2. Investigate

Inspect the smallest relevant portion of the repository.

Use exploration subagents where exploration would consume significant
main-context capacity.

### 3. Architecture

Use the architect agent when the change affects:

- multiple modules
- APIs
- database/schema
- state ownership
- authentication/authorization
- infrastructure
- new abstractions
- major frontend architecture

Skip architecture review for trivial/local changes.

### 4. Plan

Create a concise implementation specification containing:

- objective
- scope
- out of scope
- architecture decisions
- affected files/components
- acceptance criteria
- validation requirements

### 5. Implement

Delegate backend/general implementation to implementer.

Delegate substantial user-facing implementation to frontend-engineer.

Each file should have one implementation owner at a time.

### 6. Validate

After implementation run appropriate:

- tests
- type checking
- linting
- build

### 7. Independent review

After implementation:

Always use code-reviewer for substantial changes.

For user-facing changes also use:

- design-reviewer

For architecturally significant changes also use:

- architect for final architecture verification

Use verifier to validate acceptance criteria.

Review agents must never repair their own findings.

### 8. Fix

Consolidate valid findings.

Send them back to the relevant implementation agent.

Do not fix speculative/non-evidence-based findings.

### 9. Reverify

After corrections:

- rerun relevant validation
- re-review areas affected by fixes
- ensure acceptance criteria still pass

### 10. Completion

Do not tell the user a feature is finished until:

- implementation is complete
- relevant tests pass
- relevant reviewers pass
- verifier passes acceptance criteria

## Delegation policy

Use subagents when:

- work is independently executable
- specialist expertise improves quality
- exploration would pollute main context
- independent review is valuable
- tasks can safely run concurrently

Do not use subagents for:

- tiny edits
- obvious single-file changes
- simple grep/read operations
- tasks requiring constant shared state

Do not spawn agents merely to use agents.

## What this is

Care+ — an agentic active-ageing / AAC (Active Ageing Centre) outreach prototype. It learns a
personal activity baseline from wearable-style daily metrics, validates data quality, weighs context,
picks the _least intrusive permitted_ action, records the outcome, and adapts future ranking.

It is **not** a medical or emergency system. See `AGENTS.md` for the full product boundary; the short
version is below under [Invariants](#invariants).

The repo name on disk is `ismoggers`; the project everywhere else is `silverloop`.

## Layout

```
apps/api          FastAPI + SQLAlchemy 2 + Alembic (Python 3.13, uv). Owns all domain state.
apps/web          Vue 3 + Vite SPA styled with Bootstrap 5. Overview / senior / calendar / family.
                  Calendar + family (family group, appointments, availability, assignments) hold sample
                  data in the browser only: the API has no such concept yet. See UPDATES.md.
apps/e2e          Playwright browser + API tests.
libs/api-client   TypeScript SDK GENERATED from the OpenAPI snapshot. Do not hand-edit.
tools/            synthetic-data generator.
infra/supabase    Hand-applied SQL migrations mirroring the Alembic schema + RLS deny policies.
scenarios/        YAML safety scenarios (input events -> expected decisions/cases).
openapi/          Committed OpenAPI snapshot (`silverloop.json`), the cross-language contract.
docs/             architecture, api, testing, supabase, observability, demo-runbook, setup, …
physical-ai/orca  Detachable spike, README only.
```

Tooling: pnpm 11 workspace + thin Nx 23 for task orchestration; `uv` for Python. Node 24, Python 3.13.

## Commands

Always run through the root `package.json` scripts (they route to Nx targets), not raw `uvicorn`/`next`.

```bash
pnpm setup            # bootstrap: .env from template, pnpm install, playwright chromium, uv sync
pnpm dev              # web + api in parallel (web :3000, api :8000)
pnpm demo:offline     # SQLite + fixture + LLM off fallback; the only sanctioned non-Postgres run
pnpm verify           # format:check, client:check, lint, typecheck, test, test:scenarios, build
pnpm test             # python unit/API tests + e2e
pnpm test:postgres    # needs SILVERLOOP_POSTGRES_TEST_URL; db name must contain "test"
pnpm test:scenarios   # YAML scenarios under scenarios/
pnpm client:generate  # regenerate openapi/silverloop.json + libs/api-client/src/generated
pnpm client:check     # fails if the generated contract is stale or uncommitted
pnpm demo:smoke       # in-process deterministic loop smoke
pnpm demo:supabase-smoke
```

`pnpm verify` mirrors CI (`.github/workflows/ci.yml`). Run it, or at minimum
`pnpm format:check && pnpm client:check && pnpm lint && pnpm typecheck && pnpm test`, before opening a PR.

## Invariants

Break these and the change is wrong, regardless of how well it works.

**Product boundary.** No diagnosis, disease prediction, fall detection, emergency dispatch,
medication advice, unconsented caregiver contact, or interpreting heart rate / SpO2 as a medical
signal.

**Architecture.**

- FastAPI owns every domain state transition and every domain DB write.
- The Vue web app calls the API with Axios, only through `apps/web/src/services/careApi.ts` (one
  instance in `services/http.ts`), typed with the generated client's types. Sign-in still uses the
  generated client. Supabase JS is for sign-in only and never touches Supabase tables (the DB has
  explicit deny policies for `anon` and `authenticated`).
- The browser's only other calls are display-only public data in `services/publicApis.ts`
  (data.gov.sg 2-hour forecast, Nager.Date holidays): no key, no token, nothing about the senior
  sent, and the page must still work when they fail.
- Pydantic → OpenAPI → generated TS SDK is the one contract path. Change `models.py`, then run
  `pnpm client:generate` and commit both artifacts.
- SQLAlchemy 2 + Alembic own the schema. No Prisma. Do not rewrite applied migrations.
- Safety and consent rules are deterministic (`policy.py`); an LLM can never bypass them.
- The full demo must work with SQLite + fixture adapters + `LLM_ENABLED=false`.
- Every piece of evidence carries source, timestamp, confidence and an evidence ID.
- `NO_ACTION` is a first-class audited result, never an error or a silent skip.
- The Beta-Bernoulli learner (`learning.py`) only _ranks_ candidates the policy already permitted.
  It can never flip a consent, quality, confidence, contact-cap, stale-programme or review gate.

**Data.** Never commit credentials, raw wearable exports, real senior data or interview identifiers.
Label synthetic / fixture / replayed / future integrations honestly. Healthy 365 and real AAC
integrations are future, authorised adapters only.

## API internals worth knowing

`apps/api/src/silverloop/`:

- `main.py` — FastAPI app factory, routes, lifespan (runtime check → `alembic upgrade head` → seed).
- `models.py` — Pydantic contract. **Editing this changes the public contract.**
- `db_models.py` / `sql_repository.py` — SQLAlchemy schema and the single large repository
  implementation (~1.3k lines) behind the `SilverLoopRepository` Protocol in `repository.py`.
- `policy.py` — the deterministic decision ladder. `Decision` is one of `suppress`, `no_action`,
  `gentle_nudge`, `programme_suggestion`, `coordinator_review`; gates are checked in order
  (consent → data quality → confidence → rain context → severity/persistence → contact cap).
- `analytics.py` (median/MAD baseline), `quality.py` (8h minimum wear-time gate), `learning.py`.
- `triage.py` — the caregiver care-priority board (`GET /v1/coordinator/priorities`). Rules-only and
  read-only; its contact windows are capped by the day's recorded policy decision. See
  `docs/care-priorities.md`.
- `review_threshold.py` / `review_threshold_replay.py` — the per-senior review setting (when a human is
  asked), its fixed bounds, absolute floor, stateless shadow check, guardrail and fixed-rule proposer.
  Pure; `policy.decide` takes the live setting as an input and a coordinator approves every change.
  See ADR 0008 and `docs/review-threshold-spec.md`.
- `review_lessons.py` — what each review teaches (`classify_review`), the review-setting receipt
  (`build_receipt`) and the per-person context-gap tally. Pure, computed on read; `policy`,
  `review_threshold` and `agent/` must never import it (tested). See ADR 0009, `CONTEXT.md`.
- `case_delta.py` — the server-produced "since your last review" delta on `ReviewCase`. Pure, over
  append-only rows; never anything the senior said, a note or a step figure.
- `stored_state.py` / `error_responses.py` — stored simulation snapshots from an older contract raise
  `StoredStateIncompatible`; app-level handlers return classified 500 bodies
  `{code, message, detail}` (`stored_state_incompatible`, `internal_error`) with no raw framework text.
- `evaluation/calibration/` — synthetic review-setting calibration with simulated coordinator profiles
  on in-memory SQLite (`pnpm evaluate` / `evaluate:check`, output `docs/evaluation/review-calibration.*`).
  Not imported by `silverloop.evaluation`.
- `runtime.py` — refuses to start with SQLite under the `shared` profile, or with the committed
  placeholder DATABASE_URL. This guard is deliberate; don't relax it to make a run succeed.
- `adapters/` — `synthetic` (default) and `csv_sample`; provider-neutral and detachable.
- `scenarios.py`, `seed.py`, `smoke.py`, `supabase_smoke.py` — CLI entrypoints (`python -m silverloop.X`).

Simulation accepts only `activity_declines`, `rain_explains_decline`, `recovery`, `low_wear`,
`consent_revoked`. Browser calls pass an `event_id` and are idempotent per run.

## Runtime profiles

`CAREPLUS_RUNTIME_PROFILE=shared` (default) requires a PostgreSQL/Supabase `DATABASE_URL`. The older
`SILVERLOOP_RUNTIME_PROFILE` is still read when the new name is unset; launchers that force
`offline` (`demo-offline.mjs`, `playwright.config.ts`) set both so a `.env` cannot override them.
`offline` requires SQLite **and** `ADAPTER_MODE=fixture` **and** `LLM_ENABLED=false`.
Copy `.env.example` → `.env` and supply a real server-side Supabase URL locally; never commit it.
`/health` is liveness; `/ready` also checks DB connectivity and that the live Alembic revision
matches the repo head.

## Conventions

- Python: ruff (line length 100, `E,F,I,UP,B,SIM`), `from __future__ import annotations` in most
  modules, `python -m compileall` stands in for typecheck. Prettier formats everything else.
- Web: Vue SFCs with `<script setup lang="ts">`. Bootstrap classes before custom CSS; rules Bootstrap
  cannot express go in that component's `<style scoped>`. No new dependency without a reason.
  `pnpm typecheck` runs `vue-tsc` with unused imports as errors (there is no ESLint in `apps/web`).
- Branches: short-lived `feat/`, `fix/`, `test/`, `docs/` off `main`; conventional commit prefixes.
  Schema and safety-policy changes need a reviewer.
- Every behavioural change needs a scenario or test update — add to `scenarios/*.yaml` for policy
  behaviour, `apps/api/tests/` for units and API, `apps/e2e/tests/` for the browser loop.
- Prefer completing one observable loop over adding breadth.

## Further reading

`AGENTS.md` (repo instructions), `CONTRIBUTING.md` (workflow, ownership), `docs/architecture.md`,
`docs/api.md`, `docs/testing.md`, `docs/supabase.md`, `docs/observability.md`,
and `docs/demo-runbook.md`.
