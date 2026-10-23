from __future__ import annotations

from datetime import UTC, datetime, time

from silverloop.adapters.base import AdapterBatch
from silverloop.adapters.models import CanonicalDailyMetric, SourceClassification
from silverloop.fixtures import DEMO_PERSON_ID, persona_profile, synthetic_history


class SyntheticFixtureAdapter:
    """Generates one person's deterministic fixture history.

    `person_id` selects the persona's generation parameters (F5); `seed` is the RNG seed, already
    resolved through `silverloop.fixtures.persona_seed` by the caller. Defaulting `person_id` to
    `DEMO_PERSON_ID` keeps every pre-F5 call site (and `test_adapters.py`) unchanged.
    """

    def __init__(self, seed: int = 2026, person_id: str = DEMO_PERSON_ID) -> None:
        self.seed = seed
        self.person_id = person_id

    def read(self) -> AdapterBatch:
        history, current = synthetic_history(self.seed, persona_profile(self.person_id))
        metrics = [
            CanonicalDailyMetric(
                evidence_id=f"wearable_{metric.day.isoformat()}_synthetic",
                day=metric.day,
                observed_at=datetime.combine(metric.day, time(hour=12), tzinfo=UTC),
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
