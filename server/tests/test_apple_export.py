"""Apple Health export adapter.

Every test here runs against a small inline XML fixture we construct ourselves, so the suite
stays green on machines without a real export. The one test that reads a genuine export is
skipped cleanly (`pytest.mark.skipif`) when the file is absent, per the spec's requirement that
CI never depends on it. The real export path, if present, is never committed and lives outside
the repository under `data/exports/`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from silverloop.adapters import AppleHealthExportAdapter, SourceClassification

REAL_EXPORT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "exports" / "apple_health_export" / "export.xml"
)


def _write_export(tmp_path: Path, records: str) -> Path:
    export_path = tmp_path / "export.xml"
    export_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
{records}
</HealthData>
""",
        encoding="utf-8",
    )
    return export_path


def _step_record(source: str, start: str, end: str, value: int) -> str:
    return (
        f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="{source}" '
        f'sourceVersion="1.0" unit="count" creationDate="{end}" '
        f'startDate="{start}" endDate="{end}" value="{value}"/>'
    )


def _sleep_record(source: str, start: str, end: str, value: str) -> str:
    return (
        f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="{source}" '
        f'sourceVersion="1.0" creationDate="{end}" startDate="{start}" endDate="{end}" '
        f'value="{value}"/>'
    )


def _exercise_record(source: str, start: str, end: str, value: int) -> str:
    return (
        f'<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="{source}" '
        f'sourceVersion="1.0" unit="min" creationDate="{end}" startDate="{start}" '
        f'endDate="{end}" value="{value}"/>'
    )


def _irrelevant_record(start: str, end: str) -> str:
    return (
        '<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Ian’s Watch" '
        f'sourceVersion="1.0" unit="count/min" creationDate="{end}" startDate="{start}" '
        f'endDate="{end}" value="61"/>'
    )


def test_missing_consent_reference_rejected(tmp_path: Path) -> None:
    export_path = _write_export(tmp_path, "")
    with pytest.raises(ValueError, match="consent reference"):
        AppleHealthExportAdapter(export_path, consent_reference="")


def test_export_with_no_relevant_records_raises(tmp_path: Path) -> None:
    export_path = _write_export(
        tmp_path, _irrelevant_record("2026-01-01 08:00:00 +0000", "2026-01-01 08:01:00 +0000")
    )
    with pytest.raises(ValueError, match="no step, exercise or sleep"):
        AppleHealthExportAdapter(export_path, consent_reference="team-member-demo-consent").read()


def test_ignores_record_types_outside_the_three_permitted(tmp_path: Path) -> None:
    records = "\n".join(
        [
            _irrelevant_record("2026-01-01 08:00:00 +0000", "2026-01-01 08:01:00 +0000"),
            _step_record("Watch", "2026-01-01 08:00:00 +0000", "2026-01-01 08:05:00 +0000", 500),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    assert len(batch.metrics) == 1
    assert batch.metrics[0].steps == 500


def test_single_source_day_passes_through_unchanged(tmp_path: Path) -> None:
    """No overlap, no other source: the naive and deduplicated totals must match."""
    records = "\n".join(
        [
            _step_record("Phone", "2026-01-01 08:00:00 +0000", "2026-01-01 08:05:00 +0000", 500),
            _step_record("Phone", "2026-01-01 09:00:00 +0000", "2026-01-01 09:05:00 +0000", 300),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    assert batch.metrics[0].steps == 800
    assert batch.metrics[0].ingestion_confidence == 0.9


def test_overlapping_watch_and_phone_intervals_are_deduplicated_not_summed(
    tmp_path: Path,
) -> None:
    """The core correctness property: a fully overlapping second device must not add steps."""
    records = "\n".join(
        [
            _step_record(
                "Ian’s Watch",
                "2026-01-01 08:00:00 +0000",
                "2026-01-01 08:10:00 +0000",
                1000,
            ),
            # Fully overlapping interval from a lower-priority phone reporting the *same* walk.
            _step_record(
                "Samsung Phone",
                "2026-01-01 08:00:00 +0000",
                "2026-01-01 08:10:00 +0000",
                950,
            ),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()

    naive_sum = 1000 + 950
    deduped = batch.metrics[0].steps
    assert deduped == 1000  # only the higher-priority watch interval is credited
    assert deduped < naive_sum
    assert batch.metrics[0].ingestion_confidence == 0.75  # multi-source day: lower confidence


def test_partially_overlapping_phone_interval_only_credits_uncovered_time(
    tmp_path: Path,
) -> None:
    records = "\n".join(
        [
            # Watch covers the first half of a 10-minute window.
            _step_record(
                "Ian’s Watch",
                "2026-01-01 08:00:00 +0000",
                "2026-01-01 08:05:00 +0000",
                500,
            ),
            # Phone reports the full 10-minute window at a uniform rate (100 steps/min).
            _step_record(
                "Samsung Phone",
                "2026-01-01 08:00:00 +0000",
                "2026-01-01 08:10:00 +0000",
                1000,
            ),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    # Watch: 500 in full. Phone: only its uncovered second half (5 of 10 minutes) counts,
    # pro-rated: 1000 * (5/10) = 500. Total = 1000, not the naive 1500.
    assert batch.metrics[0].steps == 1000


def test_wear_hours_is_distinct_hours_with_a_step_sample(tmp_path: Path) -> None:
    records = "\n".join(
        [
            _step_record("Phone", "2026-01-01 07:50:00 +0000", "2026-01-01 08:05:00 +0000", 200),
            _step_record("Phone", "2026-01-01 12:00:00 +0000", "2026-01-01 12:02:00 +0000", 50),
            _step_record("Phone", "2026-01-01 20:00:00 +0000", "2026-01-01 20:01:00 +0000", 10),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    # Hours touched: 7, 8 (first interval spans the boundary), 12, 20 -> 4 distinct hours.
    assert batch.metrics[0].wear_hours == 4
    assert "DERIVED PROXY" in batch.disclosure


def test_low_wear_day_is_not_fabricated_to_pass_the_quality_gate(tmp_path: Path) -> None:
    """A single short interval in one hour must read as low wear, not a plausible constant."""
    records = _step_record("Phone", "2026-01-01 09:00:00 +0000", "2026-01-01 09:02:00 +0000", 50)
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    assert batch.metrics[0].wear_hours == 1
    assert batch.metrics[0].wear_hours < 8


def test_sleep_intervals_from_multiple_sources_are_unioned_not_summed(tmp_path: Path) -> None:
    records = "\n".join(
        [
            _sleep_record(
                "Watch",
                "2026-01-01 23:00:00 +0000",
                "2026-01-02 01:00:00 +0000",
                "HKCategoryValueSleepAnalysisAsleepCore",
            ),
            # Overlapping report of the same sleep session from a phone app.
            _sleep_record(
                "SleepApp",
                "2026-01-01 23:30:00 +0000",
                "2026-01-02 01:30:00 +0000",
                "HKCategoryValueSleepAnalysisAsleepUnspecified",
            ),
            _step_record("Phone", "2026-01-01 08:00:00 +0000", "2026-01-01 08:01:00 +0000", 10),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    day_one = next(m for m in batch.metrics if m.day.isoformat() == "2026-01-01")
    # Union of 23:00-01:00 and 23:30-01:30 is 2.5 hours, not the naive sum of 2h + 2h = 4h.
    assert day_one.sleep_hours == pytest.approx(2.5)


def test_awake_and_in_bed_states_are_excluded_from_sleep_hours(tmp_path: Path) -> None:
    records = "\n".join(
        [
            _sleep_record(
                "Watch",
                "2026-01-01 22:00:00 +0000",
                "2026-01-01 23:00:00 +0000",
                "HKCategoryValueSleepAnalysisInBed",
            ),
            _sleep_record(
                "Watch",
                "2026-01-01 23:00:00 +0000",
                "2026-01-02 00:00:00 +0000",
                "HKCategoryValueSleepAnalysisAsleepDeep",
            ),
            _step_record("Phone", "2026-01-01 08:00:00 +0000", "2026-01-01 08:01:00 +0000", 10),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    day_one = next(m for m in batch.metrics if m.day.isoformat() == "2026-01-01")
    assert day_one.sleep_hours == pytest.approx(1.0)


def test_batch_is_classified_as_consented_sample_with_disclosure(tmp_path: Path) -> None:
    records = _step_record("Phone", "2026-01-01 08:00:00 +0000", "2026-01-01 08:05:00 +0000", 500)
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    assert batch.source_classification == SourceClassification.CONSENTED_SAMPLE
    assert all(
        m.source_classification == SourceClassification.CONSENTED_SAMPLE for m in batch.metrics
    )
    assert "not retained" in batch.disclosure
    assert "team-member-demo-consent" in batch.disclosure


def test_exercise_minutes_are_deduplicated_like_steps(tmp_path: Path) -> None:
    records = "\n".join(
        [
            _exercise_record("Watch", "2026-01-01 08:00:00 +0000", "2026-01-01 08:10:00 +0000", 10),
            _exercise_record("Phone", "2026-01-01 08:00:00 +0000", "2026-01-01 08:10:00 +0000", 9),
            _step_record("Phone", "2026-01-01 08:00:00 +0000", "2026-01-01 08:01:00 +0000", 10),
        ]
    )
    export_path = _write_export(tmp_path, records)
    batch = AppleHealthExportAdapter(
        export_path, consent_reference="team-member-demo-consent"
    ).read()
    assert batch.metrics[0].active_minutes == 10  # watch (higher priority) wins the full overlap


@pytest.mark.skipif(
    not REAL_EXPORT_PATH.exists() or os.environ.get("CI") == "true",
    reason="Real Apple Health export is a private, non-CI local fixture; see data/exports/README.",
)
def test_real_export_produces_plausible_canonical_metrics() -> None:
    batch = AppleHealthExportAdapter(
        REAL_EXPORT_PATH, consent_reference="ian-personal-export-self-consent"
    ).read()
    assert len(batch.metrics) > 0
    for metric in batch.metrics:
        assert 0 <= metric.wear_hours <= 24
        assert metric.steps >= 0
        assert metric.source_classification == SourceClassification.CONSENTED_SAMPLE
    days = [metric.day for metric in batch.metrics]
    assert days == sorted(days)
    assert len(days) == len(set(days))
