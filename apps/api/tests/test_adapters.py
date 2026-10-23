from io import StringIO

import pytest

from silverloop.adapters import (
    CsvSampleAdapter,
    SampleFormat,
    SourceClassification,
    SyntheticFixtureAdapter,
)


def test_synthetic_adapter_is_deterministic_and_explicitly_classified() -> None:
    first = SyntheticFixtureAdapter(seed=2026).read()
    second = SyntheticFixtureAdapter(seed=2026).read()
    assert first == second
    assert len(first.metrics) == 29
    assert first.source_classification == SourceClassification.SYNTHETIC_FIXTURE
    assert "not a real wearable export" in first.disclosure
    assert all(metric.ingestion_confidence == 1 for metric in first.metrics)


@pytest.mark.parametrize(
    ("sample_format", "content", "expected_steps"),
    [
        (
            SampleFormat.CANONICAL_CSV,
            "day,steps,active_minutes,sleep_hours,wear_hours\n2026-08-01,5100,36,7.1,13.2\n",
            5100,
        ),
        (
            SampleFormat.APPLE_HEALTH_SAMPLE,
            "date,step_count,exercise_minutes,sleep_hours,wear_hours\n"
            "2026-08-01,5200,38,7.2,13.4\n",
            5200,
        ),
        (
            SampleFormat.GARMIN_SAMPLE,
            "calendarDate,totalSteps,activeMinutes,sleepHours,wearHours\n"
            "2026-08-01,5300,40,7.3,13.6\n",
            5300,
        ),
    ],
)
def test_consented_csv_samples_normalise_to_canonical_metrics(
    sample_format: SampleFormat, content: str, expected_steps: int
) -> None:
    batch = CsvSampleAdapter(
        StringIO(content),
        sample_format=sample_format,
        consent_reference="team-member-demo-consent",
    ).read()
    assert batch.metrics[0].steps == expected_steps
    assert batch.metrics[0].source_classification == SourceClassification.CONSENTED_SAMPLE
    assert "Raw provider exports are not retained" in batch.disclosure


def test_sample_import_rejects_missing_consent_and_duplicate_days() -> None:
    with pytest.raises(ValueError, match="consent reference"):
        CsvSampleAdapter(
            StringIO("day,steps,active_minutes,sleep_hours,wear_hours\n"),
            sample_format=SampleFormat.CANONICAL_CSV,
            consent_reference="",
        )

    duplicate = (
        "day,steps,active_minutes,sleep_hours,wear_hours\n"
        "2026-08-01,5100,36,7.1,13.2\n"
        "2026-08-01,5200,37,7.2,13.3\n"
    )
    with pytest.raises(ValueError, match="duplicate day"):
        CsvSampleAdapter(
            StringIO(duplicate),
            sample_format=SampleFormat.CANONICAL_CSV,
            consent_reference="team-member-demo-consent",
        ).read()
