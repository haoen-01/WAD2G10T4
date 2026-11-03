from datetime import datetime

from silverloop.models import DailyMetric, DataQualityAssessment

MINIMUM_WEAR_HOURS = 8


def assess_data_quality(
    metric: DailyMetric,
    *,
    person_id: str,
    assessed_at: datetime,
    self_reported_conflict: bool = False,
    self_reported_conflict_note: str | None = None,
) -> DataQualityAssessment:
    """Judge whether one day's reading can carry a behavioural interpretation.

    `self_reported_conflict` is the one input here that does not come from a sensor: the person
    has told us a day we read as quiet was not, either by disputing the day directly or by
    declining a suggestion with "I was already active". It is reported alongside the reading
    rather than replacing it -- the device said what it said, the person said what they said, and
    both are kept. It is deliberately NOT allowed to flip `safe_to_interpret`: wear-time is the
    only thing that decides whether a reading is interpretable at all, and a conflict is a caveat
    on the interpretation, not a substitute reading.
    """
    if metric.wear_hours < MINIMUM_WEAR_HOURS:
        device_suspected_reason = (
            f"Wear-time of {metric.wear_hours} hours suggests the tracker was not worn "
            "for enough of the day or did not sync; this looks like a device issue rather "
            "than a wellbeing signal."
        )
        return DataQualityAssessment(
            evidence_id=f"dq_{person_id}_{metric.day.isoformat()}_{metric.source}",
            assessed_at=assessed_at,
            source=metric.source,
            confidence=min(1.0, metric.wear_hours / MINIMUM_WEAR_HOURS),
            safe_to_interpret=False,
            reasons=[
                (
                    f"Tracker wear-time was {metric.wear_hours} hours; "
                    f"at least {MINIMUM_WEAR_HOURS} hours is required."
                )
            ],
            device_suspected=True,
            device_suspected_reason=device_suspected_reason,
            self_reported_conflict=self_reported_conflict,
            self_reported_conflict_note=self_reported_conflict_note,
        )

    return DataQualityAssessment(
        evidence_id=f"dq_{person_id}_{metric.day.isoformat()}_{metric.source}",
        assessed_at=assessed_at,
        source=metric.source,
        confidence=1.0,
        safe_to_interpret=True,
        reasons=["Tracker worn long enough to use."],
        self_reported_conflict=self_reported_conflict,
        self_reported_conflict_note=self_reported_conflict_note,
    )
