# Local-only wearable exports

Drop a consented personal wearable export here (Apple `export.xml`, Garmin `.fit`).

**Everything in this directory except this README is gitignored and must stay that way.**
A real Apple Health or Garmin export contains identifiable personal health data. The repository
rules forbid committing raw wearable exports, real senior data, or interview identifiers — see
`AGENTS.md` and `docs/data-and-privacy.md`.

Adapters read from here to prove real-world normalisation. The normalised output is bounded to the
canonical daily fields (day, steps, active minutes, sleep hours, wear hours, source) and the raw
file is never retained, copied into the repo, or included in any artifact.
