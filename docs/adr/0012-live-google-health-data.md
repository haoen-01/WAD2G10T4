# 0012. Live Google Health data is steps only and never mixed with sample data

Status: Accepted (2026-10-26). Depends on getting Google Health API access, tested in a half-day
spike on day 1; if access is blocked the demo runs on sample data alone. Amended 2026-10-29: how
live mode runs by itself (see "How live mode runs" below and `docs/research/live-sync-scheduling.md`).

A real senior account can be linked to that senior's own Google account, and Care+ then reads their
daily steps (plus wear time, if Google provides it) and labels them _Live_. Only the senior can
connect or disconnect, from their own screen; disconnecting stops the sync and keeps the history
already read. The Google token stays on the API server, encrypted, and the browser only ever sees
"connected / not connected / last synced". Live data is never committed.

The sample seniors keep their generated data, labelled _Sample_. When the live sync fails, the live
senior keeps their real history and shows when it last updated; the fallback is switching to the
sample family group, never filling the live senior's days with sample data. We chose this over
swapping in sample data because a Baseline that mixes real and generated days is quietly wrong and
breaks the Sample/Live labelling.

## Consequences

- Heart rate, blood oxygen and sleep are not fetched at all, which is the simplest way to keep
  within the rule against reading them as medical signals.
- If Google gives no wear-time signal, live days count as unknown wear, the data-quality gate holds,
  and the live senior gets no suggestions. Counting any day with steps as worn, or inferring wear
  from the presence of heart-rate readings, would weaken or edge around a safety gate, so either one
  needs a reviewer and its own ADR.
- Live mode fetches yesterday's final steps nightly (Singapore time) and runs that day's decision;
  opening the app refreshes today's partial count for display only. Sample seniors are never synced
  or scheduled.

## How live mode runs (amended 2026-10-29)

- **What runs it.** An external timer calls one protected route, `POST /v1/internal/live-sync`, at
  02:17 Singapore time: a GitHub Actions scheduled workflow (`timezone: Asia/Singapore`), or
  Supabase Cron if the API is hosted beside Supabase. Nothing is scheduled inside the FastAPI
  process: it would not fire on a host that sleeps when idle, and two processes would run it twice.
  FastAPI still does all the work and owns every write.
- **What the route does.** Only with the right `X-Care-Sync-Token`, and never in the `offline`
  profile (404 there). For each senior with a connected Google account, it syncs every finished
  Singapore day since the last synced one up to yesterday, then runs that day's decision with a
  fixed `event_id`. A late, missed or doubled run is caught up or ignored.
- **Today on app open.** `GET /v1/people/{person_id}/steps-today` reads today's count so far for
  display only. It is never stored as the day's reading and never reaches `policy.py`.
- **Failures.** Each run is recorded per senior (status, short error code, days synced). The watch
  status gains `source: "live"`, `last_sync_status` and `last_sync_error`, so the screen says
  "Steps last updated 2:17 am" or "Couldn't update last night. Showing steps up to Tuesday."
- **Never the demo.** Sample and demo seniors have no Google link, so they are never selected. The
  offline profile has no route at all. Each of these has an API test.
- **Still open.** Where the API is hosted, and whether yesterday's count is final by 02:17 (decide
  after the day-1 Google access spike).
