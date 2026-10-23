from datetime import UTC, date, datetime

from silverloop.models import DailyMetric
from silverloop.quality import assess_data_quality

ASSESSMENT_TIME = datetime(2026, 8, 19, 12, tzinfo=UTC)


def test_low_wear_time_is_not_safe_to_interpret() -> None:
    metric = DailyMetric(
        day=date(2026, 8, 19),
        steps=500,
        active_minutes=4,
        sleep_hours=None,
        wear_hours=2,
        source="synthetic",
    )

    result = assess_data_quality(
        metric,
        person_id="mdm-lim",
        assessed_at=ASSESSMENT_TIME,
    )

    assert result.safe_to_interpret is False
    assert result.confidence == 0.25
    assert result.source == "synthetic"
    assert result.evidence_id == "dq_mdm-lim_2026-08-19_synthetic"
    assert "wear-time" in result.reasons[0]
    assert result.device_suspected is True
    assert result.device_suspected_reason is not None


def test_normal_wear_time_is_safe_to_interpret() -> None:
    metric = DailyMetric(
        day=date(2026, 8, 19),
        steps=5500,
        active_minutes=40,
        sleep_hours=7,
        wear_hours=13,
        source="synthetic",
    )

    result = assess_data_quality(
        metric,
        person_id="mdm-lim",
        assessed_at=ASSESSMENT_TIME,
    )

    assert result.safe_to_interpret is True
    assert result.confidence == 1.0
    assert result.evidence_id == "dq_mdm-lim_2026-08-19_synthetic"
    assert result.device_suspected is False
    assert result.device_suspected_reason is None


def test_evidence_id_does_not_collide_across_people_on_the_same_day() -> None:
    """Two people assessed on the same day/source must not share an evidence ID (F2 bug #2)."""
    metric = DailyMetric(
        day=date(2026, 8, 19),
        steps=5500,
        active_minutes=40,
        sleep_hours=7,
        wear_hours=13,
        source="synthetic",
    )

    result_a = assess_data_quality(metric, person_id="mdm-lim", assessed_at=ASSESSMENT_TIME)
    result_b = assess_data_quality(metric, person_id="mr-tan", assessed_at=ASSESSMENT_TIME)

    assert result_a.evidence_id != result_b.evidence_id


def test_zero_steps_with_good_wear_time_is_not_device_suspected() -> None:
    """A genuinely inactive day with sufficient wear-time is a real, interpretable low-activity
    signal -- not evidence that the tracker failed -- so `device_suspected` must stay False even
    though `steps` is zero."""
    metric = DailyMetric(
        day=date(2026, 8, 19),
        steps=0,
        active_minutes=0,
        sleep_hours=8,
        wear_hours=14,
        source="synthetic",
    )

    result = assess_data_quality(metric, person_id="mdm-lim", assessed_at=ASSESSMENT_TIME)

    assert result.safe_to_interpret is True
    assert result.device_suspected is False
    assert result.device_suspected_reason is None


def test_zero_steps_with_poor_wear_time_is_device_suspected() -> None:
    """The same zero-step day, but with wear-time below the minimum, looks like a dead or
    unsynced tracker (playbook scenario #5, "flat battery") rather than a real activity signal,
    so `device_suspected` must be True."""
    metric = DailyMetric(
        day=date(2026, 8, 19),
        steps=0,
        active_minutes=0,
        sleep_hours=None,
        wear_hours=0,
        source="synthetic",
    )

    result = assess_data_quality(metric, person_id="mdm-lim", assessed_at=ASSESSMENT_TIME)

    assert result.safe_to_interpret is False
    assert result.device_suspected is True
    assert result.device_suspected_reason is not None
