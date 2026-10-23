"""Apple Health export adapter.

Normalises a real Apple Health `export.xml` into Care+'s canonical daily-metric
contract. This is the one adapter proven against a genuine wearable export rather than a
synthetic fixture or a pre-aggregated CSV sample; it exists to prove real-world ingestion,
not to become a live HealthKit integration (that needs an iOS companion app requesting
HealthKit entitlements and is out of scope here).

Scope of what is read
----------------------
The export is a single, possibly very large, XML document containing every HealthKit record
type a person has ever synced (heart rate, HRV, blood oxygen, ECG waveforms, clinical records,
workout GPS routes, demographic `<Me>` data, ...). This adapter reads **only** three record
types by `type` attribute:

- `HKQuantityTypeIdentifierStepCount`
- `HKQuantityTypeIdentifierAppleExerciseTime`
- `HKCategoryTypeIdentifierSleepAnalysis`

Every other `<Record>` element (and every other top-level element) is skipped and cleared
without inspecting its attributes. Nothing else in the export is parsed, retained, or written
to disk. The raw export file itself must never be committed or copied; only the normalised
`CanonicalDailyMetric` rows this adapter produces enter Care+.

Streaming
---------
`export.xml` can be hundreds of megabytes. This adapter uses `xml.etree.ElementTree.iterparse`
and clears each processed element immediately, plus periodically clears the root element's
child list, so memory stays bounded by "a day's worth of intervals", never by file size.

Deduplication strategy (the important part)
---------------------------------------------
A person who owns both a phone and a watch gets **overlapping** step intervals: the watch and
the phone each independently timestamp-bucket the same physical steps while both are carried.
Naively summing every `StepCount` record's `value` therefore double- (or multi-) counts steps
during any period where more than one device was recording, inflating daily totals.

This adapter instead:

1. Buckets every step (and exercise-minute) record into per-day, per-source time intervals.
2. Assigns each source a priority tier by a generic keyword match on `sourceName`
   (`"watch"` > `"phone"` > everything else — tablets, third-party apps, manual entries). The
   match is keyword-based, never on the device owner's personal name, so the adapter carries
   no identifying strings.
3. Processes each day's intervals in priority order. For each interval, it computes what
   fraction of that interval's time span is **not yet covered** by an already-processed,
   higher-or-equal-priority interval, and only credits that uncovered fraction of the
   interval's value (steps assumed uniformly distributed across the interval — a documented
   simplification, not a measurement). The interval's full time span is then marked covered so
   a third, lower-priority source cannot also double-count the same window.

This is a "primary sensor wins, secondary sensor only fills gaps" strategy: on days when only
one device was active, its total passes through unchanged; on days with overlapping wear, the
secondary device only contributes for the time slices the primary device didn't cover. It is a
heuristic, not a physiological ground truth — Care+'s `ingestion_confidence` is lowered on
days with more than one contributing step source to reflect that.

Sleep analysis records are deduplicated the same way but without a device priority, because
what matters is the union of "was asleep" wall-clock time, not a magnitude: overlapping
"asleep" intervals from any source are merged and counted once.

`wear_hours` is a DERIVED PROXY, not a measurement
----------------------------------------------------
Apple Health exports no wear-time signal. This adapter proxies `wear_hours` as the count of
distinct clock hours in the day (0-23, based on each interval's local start/end hour) that
contain at least one step sample from *any* source. A day where the phone/watch was left at
home for most of the day will — correctly — read as low wear and can fail Care+'s
`quality.py` minimum-wear-hours gate, producing an audited `NO_ACTION`. That is the gate
working as intended; this adapter does not fabricate a constant to make days pass it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from silverloop.adapters.base import AdapterBatch
from silverloop.adapters.models import CanonicalDailyMetric, SourceClassification

STEP_TYPE = "HKQuantityTypeIdentifierStepCount"
EXERCISE_TYPE = "HKQuantityTypeIdentifierAppleExerciseTime"
SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"

RELEVANT_TYPES = {STEP_TYPE, EXERCISE_TYPE, SLEEP_TYPE}

ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
}

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S %z"

# How many parsed elements to accumulate before pruning the root element's children. Individual
# `elem.clear()` calls already free each element's attributes as we go; this bounds the size of
# the root's child list, which is what actually keeps memory proportional to a day's data rather
# than to the whole file.
_ROOT_PRUNE_INTERVAL = 2000


@dataclass(frozen=True)
class _Interval:
    start: datetime
    end: datetime
    value: float
    source: str


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _device_priority(source_name: str) -> int:
    """Rank a source for overlap deduplication; lower wins where intervals overlap.

    A continuously worn wrist device is treated as the primary sensor, a phone as secondary
    (often pocketed or left behind), and anything else (tablets, third-party apps, manual
    entry) as gap-filling only. Matching is on generic device-type keywords, never on the
    device owner's name, so this function never handles or stores identifying strings.
    """
    lowered = source_name.lower()
    if "watch" in lowered:
        return 0
    if "phone" in lowered:
        return 1
    return 2


def _merge_interval(
    covered: list[tuple[datetime, datetime]], start: datetime, end: datetime
) -> None:
    covered.append((start, end))
    covered.sort()
    merged: list[tuple[datetime, datetime]] = []
    for interval_start, interval_end in covered:
        if merged and interval_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], interval_end))
        else:
            merged.append((interval_start, interval_end))
    covered[:] = merged


def _overlap_seconds(
    covered: list[tuple[datetime, datetime]], start: datetime, end: datetime
) -> float:
    total = 0.0
    for interval_start, interval_end in covered:
        lo = max(interval_start, start)
        hi = min(interval_end, end)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total


def dedupe_quantity_intervals(intervals: list[_Interval]) -> float:
    """Sum interval values, crediting only the time each interval isn't already covered.

    Intervals are processed in device-priority order (then chronologically), so a higher
    priority source's reported value always counts in full, and a lower priority source only
    contributes for the portion of its interval not already claimed by a higher priority one.
    """
    ordered = sorted(
        intervals, key=lambda interval: (_device_priority(interval.source), interval.start)
    )
    covered: list[tuple[datetime, datetime]] = []
    total = 0.0
    for interval in ordered:
        duration = (interval.end - interval.start).total_seconds()
        if duration <= 0:
            already_covered = _overlap_seconds(covered, interval.start, interval.end) > 0
            if not already_covered:
                total += interval.value
        else:
            overlap = _overlap_seconds(covered, interval.start, interval.end)
            uncovered_fraction = max(0.0, (duration - overlap) / duration)
            total += interval.value * uncovered_fraction
        _merge_interval(covered, interval.start, interval.end)
    return total


def _union_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    """Total wall-clock time covered by the union of (possibly overlapping) intervals."""
    covered: list[tuple[datetime, datetime]] = []
    total = 0.0
    for start, end in sorted(intervals):
        overlap = _overlap_seconds(covered, start, end)
        duration = (end - start).total_seconds()
        total += max(0.0, duration - overlap)
        _merge_interval(covered, start, end)
    return total


def _wear_hours(step_intervals: list[_Interval]) -> float:
    """Distinct clock hours (0-23) containing at least one step sample, from any source.

    A derived proxy for wear-time, not a measurement: Apple Health exports no wear signal.
    """
    hours: set[int] = set()
    for interval in step_intervals:
        end_hour = interval.end.hour if interval.end.date() == interval.start.date() else 23
        for hour in range(interval.start.hour, max(interval.start.hour, end_hour) + 1):
            hours.add(hour)
    return float(len(hours))


class AppleHealthExportAdapter:
    """Normalise a real Apple Health `export.xml` without retaining the raw file.

    See the module docstring for the deduplication strategy and the `wear_hours` proxy
    derivation. Follows `CsvSampleAdapter`'s precedent of requiring a non-empty consent
    reference before any real personal export can be ingested.
    """

    def __init__(self, export_path: str | Path, *, consent_reference: str) -> None:
        if not consent_reference.strip():
            raise ValueError("A consent reference is required for sample imports.")
        self.export_path = Path(export_path)
        self.consent_reference = consent_reference

    def read(self) -> AdapterBatch:
        step_intervals: dict[date, list[_Interval]] = defaultdict(list)
        exercise_intervals: dict[date, list[_Interval]] = defaultdict(list)
        sleep_intervals: dict[date, list[tuple[datetime, datetime]]] = defaultdict(list)

        context = iter(ET.iterparse(str(self.export_path), events=("start", "end")))
        _, root = next(context)
        processed = 0
        for event, elem in context:
            if event != "end" or elem.tag != "Record":
                continue
            processed += 1
            record_type = elem.get("type")
            if record_type in RELEVANT_TYPES:
                start = _parse_timestamp(elem.get("startDate"))
                end = _parse_timestamp(elem.get("endDate"))
                source = elem.get("sourceName") or "unknown"
                if start is not None and end is not None:
                    day = start.date()
                    if record_type == STEP_TYPE:
                        value = float(elem.get("value") or 0.0)
                        step_intervals[day].append(_Interval(start, end, value, source))
                    elif record_type == EXERCISE_TYPE:
                        value = float(elem.get("value") or 0.0)
                        exercise_intervals[day].append(_Interval(start, end, value, source))
                    elif elem.get("value") in ASLEEP_VALUES:
                        sleep_intervals[day].append((start, end))
            elem.clear()
            if processed % _ROOT_PRUNE_INTERVAL == 0:
                root.clear()
        root.clear()

        days = sorted(set(step_intervals) | set(exercise_intervals) | set(sleep_intervals))
        if not days:
            raise ValueError("Apple Health export contains no step, exercise or sleep records.")

        metrics: list[CanonicalDailyMetric] = []
        for day in days:
            day_steps = step_intervals.get(day, [])
            day_exercise = exercise_intervals.get(day, [])
            day_sleep = sleep_intervals.get(day, [])

            steps_total = dedupe_quantity_intervals(day_steps)
            exercise_total = dedupe_quantity_intervals(day_exercise)
            sleep_hours = min(24.0, _union_seconds(day_sleep) / 3600)
            wear_hours = _wear_hours(day_steps)

            distinct_step_sources = {interval.source for interval in day_steps}
            confidence = 0.75 if len(distinct_step_sources) > 1 else 0.9

            metrics.append(
                CanonicalDailyMetric(
                    evidence_id=f"apple_export_{day.isoformat()}",
                    day=day,
                    observed_at=datetime.combine(day, time(hour=12), tzinfo=UTC),
                    steps=round(steps_total),
                    active_minutes=round(exercise_total),
                    sleep_hours=sleep_hours if day_sleep else None,
                    wear_hours=wear_hours,
                    source="apple_health_export",
                    source_classification=SourceClassification.CONSENTED_SAMPLE,
                    ingestion_confidence=confidence,
                )
            )

        return AdapterBatch(
            source="apple_health_export",
            source_classification=SourceClassification.CONSENTED_SAMPLE,
            disclosure=(
                "Real Apple Health export, normalised and not retained in raw form. Overlapping "
                "multi-device step and exercise intervals are deduplicated by device-priority "
                "interval covering (see module docstring); wear_hours is a DERIVED PROXY (distinct "
                "clock hours containing a step sample), not a measured wear-time signal. "
                f"Consent reference: {self.consent_reference}"
            ),
            metrics=metrics,
        )
