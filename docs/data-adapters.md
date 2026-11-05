# Detachable daily-metrics adapters

Care+ analytics accepts one provider-neutral daily record: day, observation timestamp, steps,
active minutes, optional sleep hours, wear hours, source, source classification, ingestion
confidence and evidence ID. Provider adapters normalise into that contract; they do not change the
deterministic policy.

## Supported now

### Synthetic fixture

`SyntheticFixtureAdapter` is the default and the only adapter required by the hackathon demo. It
produces 29 deterministic days labelled `synthetic_fixture`, includes a plain disclosure, and works
offline. Its days end on Tue 18 Aug 2026 (`fixtures.DEMO_ANCHOR_DAY`). A demo reset with
`DEMO_DATES_FOLLOW_TODAY=true` (the default) asks it to end on today in Singapore instead: every day
moves by the same number of days, the values and their order do not change, and no moved reading
is stamped later than the moment it was written. Without that, the fixture's own days and
midday-UTC stamps are written whatever the clock says. Only synthetic fixture readings are ever
moved. A day the simulation advances onto today is also held at the moment it was written, never
before that day's midnight UTC, because the loop reads a decision's day from that date: between
midnight and 8 am in Singapore its stamp can be up to eight hours ahead of the clock. Later
simulated days keep midday UTC.

### Consented sample CSV

`CsvSampleAdapter` accepts an in-memory, pre-aggregated sample only when a non-empty consent
reference is supplied. It supports these header shapes:

| Format              | Required daily columns                                                   |
| ------------------- | ------------------------------------------------------------------------ |
| Canonical CSV       | `day`, `steps`, `active_minutes`, `sleep_hours`, `wear_hours`            |
| Apple Health sample | `date`, `step_count`, `exercise_minutes`, `sleep_hours`, `wear_hours`    |
| Garmin sample       | `calendarDate`, `totalSteps`, `activeMinutes`, `sleepHours`, `wearHours` |

This is a sample-normalisation proof, not a live provider integration. The adapter retains no raw
file, rejects missing columns and duplicate days, and labels records `consented_sample`. Never add
sample exports to Git; use team-owned consented data outside the repository only if the team has
explicitly approved that proof.

### Real Apple Health export

`AppleHealthExportAdapter` streams a genuine Apple Health `export.xml` with
`xml.etree.ElementTree.iterparse` (never loading the file into memory) and normalises it to the
canonical contract, labelled `consented_sample`, only when a non-empty consent reference is
supplied. It reads exactly three record types — `HKQuantityTypeIdentifierStepCount`,
`HKQuantityTypeIdentifierAppleExerciseTime`, `HKCategoryTypeIdentifierSleepAnalysis` — and ignores
everything else in the export, including heart rate, HRV, blood oxygen, ECG, workout GPS routes,
clinical records and the `<Me>` demographic block.

This proves real-world wearable ingestion; it is **not** a live HealthKit integration (that needs
an iOS companion app requesting HealthKit entitlements and syncing over time, which is out of scope
here). The raw export file is never retained, copied or committed; only the normalised daily
records enter Care+.

Two correctness properties matter more than usual for this adapter:

- **Multi-device step deduplication.** A person who carries both a phone and a watch gets
  overlapping step intervals for the same physical activity; naively summing every `StepCount`
  record inflates daily totals. The adapter ranks sources by a generic keyword match on
  `sourceName` (`watch` > `phone` > everything else — never the device owner's name) and, per
  overlapping interval, only credits the time not already covered by a higher-priority source.
  Sleep intervals are deduplicated the same way but without a device priority: overlapping
  "asleep" time from any source is unioned, not summed. See the module docstring in
  `server/src/silverloop/adapters/apple_export.py` for the full algorithm.
- **`wear_hours` is a derived proxy, not a measurement.** Apple Health exports no wear-time signal.
  This adapter proxies it as the count of distinct clock hours in the day containing at least one
  step sample from any source. A day where the tracker was left at home correctly reads as low wear
  and can fail `quality.py`'s 8-hour gate, producing an audited `NO_ACTION` — the adapter does not
  fabricate a constant to force days past the gate.

## Healthy 365: future adapter only

Healthy 365 is documented as a strategically relevant future sensing source, not an available API.
Do not scrape the app, reverse-engineer tracker traffic, borrow credentials, or make the demo depend
on government endpoints. An implementation can begin only after authorised API access, documented
data fields and retention terms, consent design, rate limits, sandbox credentials and a security
review are obtained.

The future adapter must emit the same canonical daily contract and must not interpret heart rate,
SpO2 or any metric as a medical signal. Until those conditions are met, product copy must say
“Healthy 365-compatible future adapter”, never “integrated with Healthy 365”.
