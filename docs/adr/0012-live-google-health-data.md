# 0012. Live Google Health data is steps only and never mixed with sample data

Status: Accepted (2026-10-26). Depends on getting Google Health API access, tested in a half-day
spike on day 1; if access is blocked the demo runs on sample data alone.

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
