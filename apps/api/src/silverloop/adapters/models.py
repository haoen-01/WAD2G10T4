from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from silverloop.models import ContextSignal, DailyMetric


class SourceClassification(StrEnum):
    SYNTHETIC_FIXTURE = "synthetic_fixture"
    CONSENTED_SAMPLE = "consented_sample"
    REPLAYED_FIXTURE = "replayed_fixture"
    FUTURE_INTEGRATION = "future_integration"


class CanonicalDailyMetric(BaseModel):
    """Provider-neutral daily activity record accepted by Care+ analytics."""

    evidence_id: str
    day: date
    observed_at: datetime
    steps: int = Field(ge=0)
    active_minutes: int = Field(ge=0)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    wear_hours: float = Field(ge=0, le=24)
    source: str
    source_classification: SourceClassification
    ingestion_confidence: float = Field(ge=0, le=1)
    context: ContextSignal = Field(default_factory=ContextSignal)

    def daily_metric(self) -> DailyMetric:
        return DailyMetric(
            day=self.day,
            steps=self.steps,
            active_minutes=self.active_minutes,
            sleep_hours=self.sleep_hours,
            wear_hours=self.wear_hours,
            source=self.source,
        )
