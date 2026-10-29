# Live sync: what runs the nightly sync, and where

- Date: 29 Oct 2026
- Branch: `fix/fixpatch1`, from `dev` at `b8bd073`
- Question: ADR 0012 says live mode "fetches yesterday's final steps nightly (Singapore time) and
  runs that day's decision; opening the app refreshes today's partial count for display only.
  Sample seniors are never synced or scheduled." It does not say **what** runs that every night, how
  it fits the host, how today's partial steps are read, or how a failure shows. This note settles
  those five points.
- Sources: the code on `dev` (paths relative to `apps/api/src/silverloop/`), ADR 0012, and the
  providers' own documentation listed at the end. Nothing here is built yet: there is no Google
  Health code, no scheduler and no sync table on `dev`.

## Decision in one paragraph

An **external timer calls one protected API route** once a night at **02:17 Singapore time**. The
API does all the work itself: for every senior with a connected Google account it fetches every
finished day it has not synced yet, runs that day's decision, and records how the run went. The
timer is a **GitHub Actions scheduled workflow** (free, already where the code lives); if the API
ends up hosted next to Supabase, **Supabase Cron** calling the same route is an equal alternative.
Nothing is scheduled inside the FastAPI process. Opening the app asks the API for today's count so
far, for display only. The route does not exist in the offline profile, and the sample seniors have
no Google link, so they can never be selected.

## 1. What runs it: three options compared

| Option                                                                         | How it works                                                                                          | Fits Care+?                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. Scheduler inside FastAPI** (a timer started in `lifespan`, `main.py:175`) | The API process wakes itself at 02:17.                                                                | **No.** It only fires while a process is running. On a free host that sleeps when idle (Render's free web services "spin down if they receive no incoming traffic for 15 consecutive minutes") nothing is running at 2 am. With two API processes it runs twice. A restart at the wrong moment skips a night with no trace. |
| **B. Separate worker process**                                                 | A second, always-on process runs the schedule and calls the same code.                                | Works, but it is a second service to host and pay for, and it needs its own database access, so it is a second place that writes domain state. Too heavy for this project.                                                                                                                                                  |
| **C. External timer → protected route** (chosen)                               | A scheduler outside the app sends `POST /v1/internal/live-sync` with a secret. FastAPI does the work. | **Yes.** FastAPI still owns every write (CLAUDE.md). It works on any host, including one that sleeps: the request wakes it. It costs nothing on GitHub Actions.                                                                                                                                                             |

**The timer itself (option C):**

- **GitHub Actions `schedule`** (recommended). From GitHub's docs:
  - "By default, scheduled workflows run in UTC", but "you can optionally specify a timezone using
    an IANA timezone string", so the schedule can say `Asia/Singapore` directly.
  - "The `schedule` event can be delayed during periods of high loads … High load times include the
    start of every hour", and under enough load "some queued jobs may be dropped". Hence **02:17**,
    not 02:00, and a route that copes with a late or missed night (below).
  - "Scheduled workflows will only run on the default branch", so the workflow file must be merged
    to the repo's default branch to run.
  - "In a public repository, scheduled workflows are automatically disabled when no repository
    activity has occurred in 60 days." Fine during the project; note it for after hand-in.
- **Supabase Cron** (`pg_cron` + `pg_net`) is the alternative if the API is hosted beside Supabase.
  Supabase's docs show `cron.schedule(...)` calling `net.http_post(...)` with the secret read from
  Supabase Vault. Their own caveat: "any role that can log in to your database can read the secret
  key while the request waits" (it sits in `net.http_request_queue` until sent), so the sync secret
  must be one used for nothing else. The docs do not state the cron time zone; assume UTC and
  convert (02:17 Singapore = 18:17 UTC the day before).

## 2. How it fits the host

**The host is not recorded anywhere in the repo** (`docs/setup.md`, `docs/supabase.md` and
`README.md` only describe local runs and the Supabase database). Option C works the same for each
likely choice, which is why it is chosen:

- **A host that sleeps when idle** (for example Render's free tier): the 02:17 request wakes it.
  Render says a sleeping service takes "about a minute to spin back up", so the workflow must wait
  for it: `curl --retry 5 --retry-delay 30 --max-time 120`, and the route must answer within that.
- **An always-on host**: nothing changes.
- **Serverless functions**: the route must finish inside the platform's time limit. With few live
  seniors it does; if that ever grows, the route should sync a batch and the timer call it again.

Whoever deploys the API should add one line to `docs/setup.md` naming the host and the timer used.

## 3. The route: `POST /v1/internal/live-sync`

What it does:

- **Who may call it.** Only a caller sending header `X-Care-Sync-Token` equal to the environment
  variable `LIVE_SYNC_TOKEN`, compared in constant time. It is not a user route and takes no JWT.
  If `LIVE_SYNC_TOKEN` is unset **or** the runtime profile is `offline`, the route answers 404, as
  if it did not exist.
- **Who is synced.** Only seniors with a stored Google connection that is still connected. The
  sample seniors and the demo person never have one, so they cannot be picked (ADR 0012: "Sample
  seniors are never synced or scheduled"). Consent is still checked by `policy.py` as today.
- **Which days.** Every finished Singapore day from the day after the last synced day up to
  **yesterday**, using `local_time.local_date` (`local_time.py`, a fixed +08:00 offset). A late or
  missed night is caught up by the next run, with no catch-up code of its own. Today is never
  synced here.
- **Per day:** read the day's steps (and wear time, if Google gives it) with the Google Health
  `dailyRollUp` endpoint, which Google recommends for daily totals because it "reconciles physical
  data gaps automatically using the UTC offsets". Store them labelled _Live_, then run the day's
  decision the same way the simulation does.
- **Safe to repeat.** Each day's decision gets a fixed `event_id` such as `live:<person_id>:<date>`,
  and the API already treats a repeated `event_id` as done ("Browser calls pass an `event_id` and
  are idempotent per run", CLAUDE.md). Two runs at once are stopped by a per-person lock (or a
  unique row per person and day), so a retried or doubled timer changes nothing.
- **Answer:** counts only (`{"seniors": 3, "days_synced": 3, "failed": 0}`), never names or steps,
  because the answer ends up in the GitHub Actions log.

## 4. Today's steps when the app opens (display only)

- New read route `GET /v1/people/{person_id}/steps-today`, for the senior and their family group
  (the same role checks as reading the person today). It asks Google for today's count so far and
  answers `{"steps": 2140, "as_of": "...", "source": "live", "partial": true}`.
- **Never stored** as the day's reading and **never** passed to `policy.py`: the nightly run is the
  only thing that records a day or makes a decision. Keep the answer in memory for about five
  minutes per senior, so a busy Home page does not call Google on every refresh.
- The screen says what it is: "So far today: 2,140 steps · updated 9:40 am". If Google does not
  answer, it shows nothing new and the last-updated line explains why (below).

## 5. How a failure shows ("last updated")

- A new table `live_sync_runs`: one row per senior per run, with `started_at`, `finished_at`,
  `status` (`ok`, `failed`, `partial`), a short `error_code` (`google_unreachable`,
  `token_revoked`, `no_data_yet`, …) and `days_synced`. Stored in UTC like everything else.
- `WearableStatus` (`models.py:3921`) gains `source: "live"` alongside `"synthetic"` and two fields,
  `last_sync_status` and `last_sync_error`. `last_synced_at` becomes the end of the last successful
  run. This is a contract change: run `pnpm client:generate` and commit both artifacts.
- What people see, in words:
  - Success: "Steps last updated 2:17 am".
  - Failed night: "Couldn't update last night. Showing steps up to Tuesday." The senior's real
    history stays; it is never filled with sample data (ADR 0012).
  - Google access withdrawn: the senior's own page says "Reconnect Google"; the family sees only
    "Not updating".
- For the team: a failed run makes the workflow step fail (non-2xx answer), so it shows as a failed
  run in the repo's Actions tab.

## 6. The offline demo and sample seniors are never scheduled

Enforced three ways, each with a test:

1. Offline profile: the route answers 404 (API test with `CAREPLUS_RUNTIME_PROFILE=offline`).
2. No token configured: 404 (API test).
3. Sample and demo seniors have no Google link, so a run with only them syncs nothing and writes no
   `live_sync_runs` rows (API test). The workflow file is never run by the e2e suite.

## Open questions for the team

1. **Where is the API hosted?** This decides GitHub Actions vs Supabase Cron, and whether the
   one-minute wake-up matters.
2. **Is yesterday final at 02:17?** Google's steps page gives no figure for sync delay. If a watch
   only syncs when its phone is next unlocked, a day can be short at 2 am. Two ways out: run later
   (for example 09:17), or re-read the previous day once more on the next night before deciding.
   Decide after the day-1 Google access spike.
3. **Is the repo public?** If yes, someone must keep it active, or the schedule switches itself off
   after 60 days.

## Sources

- ADR 0012 `docs/adr/0012-live-google-health-data.md`; `CLAUDE.md` (architecture and idempotency
  rules); `local_time.py`; `main.py:175` (`lifespan`); `models.py:3921` (`WearableStatus`).
- GitHub Docs, [Events that trigger workflows: `schedule`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
  and [Scheduling issue creation](https://docs.github.com/en/actions/tutorials/manage-your-work/schedule-issue-creation).
- Supabase Docs, [Scheduling Edge Functions](https://supabase.com/docs/guides/functions/schedule-functions)
  (`pg_cron` + `pg_net` + Vault).
- Render Docs, [FAQ](https://render.com/docs/faq) (free instances spin down after 15 minutes).
- Google Health API, [Steps](https://developers.google.com/health/data-types/steps) (`dailyRollUp`,
  scope `googlehealth.activity_and_fitness.readonly`).
