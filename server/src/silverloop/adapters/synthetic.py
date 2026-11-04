from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from silverloop.adapters.base import AdapterBatch
from silverloop.adapters.models import CanonicalDailyMetric, SourceClassification
from silverloop.fixtures import DEMO_PERSON_ID, persona_profile, synthetic_history


def _observed(day: date, now: datetime | None) -> datetime:
    """Midday UTC on the reading's day (the fixture's convention), never later than `now`."""
    at = datetime.combine(day, time(hour=12), tzinfo=UTC)
    return min(at, now) if now is not None else at


class SyntheticFixtureAdapter:
    """Generates one person's deterministic fixture history.

    `person_id` selects the persona's generation parameters (F5); `seed` is the RNG seed, already
    resolved through `silverloop.fixtures.persona_seed` by the caller. Defaulting `person_id` to
    `DEMO_PERSON_ID` keeps every pre-F5 call site (and `test_adapters.py`) unchanged.
    """

    def __init__(self, seed: int = 2026, person_id: str = DEMO_PERSON_ID) -> None:
        self.seed = seed
        self.person_id = person_id

    def read(self, *, end_on: date | None = None, now: datetime | None = None) -> AdapterBatch:
        """The fixture history. With `end_on`, every day moves by one offset so the latest reading
        falls on `end_on`: the same values in the same order, only the dates change. An observed
        time that would land after `now` is held at `now`, so no reading claims to come from the
        future."""
        history, current = synthetic_history(self.seed, persona_profile(self.person_id))
        shift = end_on - current.day if end_on is not None else timedelta(0)
        metrics = [
            CanonicalDailyMetric(
                evidence_id=f"wearable_{(metric.day + shift).isoformat()}_synthetic",
                day=metric.day + shift,
                observed_at=_observed(metric.day + shift, now),
                steps=metric.steps,
                active_minutes=metric.active_minutes,
                sleep_hours=metric.sleep_hours,
                wear_hours=metric.wear_hours,
                source="synthetic",
                source_classification=SourceClassification.SYNTHETIC_FIXTURE,
                ingestion_confidence=1.0,
            )
            for metric in [*history, current]
        ]
        return AdapterBatch(
            source="synthetic",
            source_classification=SourceClassification.SYNTHETIC_FIXTURE,
            disclosure="Deterministic synthetic fixture; not a real wearable export.",
            metrics=metrics,
        )
