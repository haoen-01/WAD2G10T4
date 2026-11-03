from __future__ import annotations

import csv
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import TextIO

from silverloop.adapters.base import AdapterBatch
from silverloop.adapters.models import CanonicalDailyMetric, SourceClassification


class SampleFormat(StrEnum):
    CANONICAL_CSV = "canonical_csv"
    APPLE_HEALTH_SAMPLE = "apple_health_sample"
    GARMIN_SAMPLE = "garmin_sample"


FIELD_MAPS: dict[SampleFormat, dict[str, str]] = {
    SampleFormat.CANONICAL_CSV: {
        "day": "day",
        "steps": "steps",
        "active_minutes": "active_minutes",
        "sleep_hours": "sleep_hours",
        "wear_hours": "wear_hours",
    },
    SampleFormat.APPLE_HEALTH_SAMPLE: {
        "day": "date",
        "steps": "step_count",
        "active_minutes": "exercise_minutes",
        "sleep_hours": "sleep_hours",
        "wear_hours": "wear_hours",
    },
    SampleFormat.GARMIN_SAMPLE: {
        "day": "calendarDate",
        "steps": "totalSteps",
        "active_minutes": "activeMinutes",
        "sleep_hours": "sleepHours",
        "wear_hours": "wearHours",
    },
}


class CsvSampleAdapter:
    """Normalise a consented, pre-aggregated sample without retaining the raw export."""

    def __init__(
        self,
        stream: TextIO,
        *,
        sample_format: SampleFormat,
        consent_reference: str,
    ) -> None:
        if not consent_reference.strip():
            raise ValueError("A consent reference is required for sample imports.")
        self.stream = stream
        self.sample_format = sample_format
        self.consent_reference = consent_reference

    @staticmethod
    def _optional_float(value: str | None) -> float | None:
        return None if value is None or not value.strip() else float(value)

    def read(self) -> AdapterBatch:
        reader = csv.DictReader(self.stream)
        fields = FIELD_MAPS[self.sample_format]
        missing = sorted(set(fields.values()) - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"Sample CSV is missing columns: {', '.join(missing)}")

        metrics: list[CanonicalDailyMetric] = []
        seen_days: set[date] = set()
        for row_number, row in enumerate(reader, start=2):
            try:
                day = date.fromisoformat(row[fields["day"]])
                if day in seen_days:
                    raise ValueError(f"duplicate day {day.isoformat()}")
                seen_days.add(day)
                metrics.append(
                    CanonicalDailyMetric(
                        evidence_id=(f"sample_{self.sample_format.value}_{day.isoformat()}"),
                        day=day,
                        observed_at=datetime.combine(day, time(hour=12), tzinfo=UTC),
                        steps=int(row[fields["steps"]]),
                        active_minutes=int(row[fields["active_minutes"]]),
                        sleep_hours=self._optional_float(row[fields["sleep_hours"]]),
                        wear_hours=float(row[fields["wear_hours"]]),
                        source=self.sample_format.value,
                        source_classification=SourceClassification.CONSENTED_SAMPLE,
                        ingestion_confidence=1.0,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid sample CSV row {row_number}: {exc}") from exc
        if not metrics:
            raise ValueError("Sample CSV contains no daily metrics.")
        return AdapterBatch(
            source=self.sample_format.value,
            source_classification=SourceClassification.CONSENTED_SAMPLE,
            disclosure=(
                "Consented, pre-aggregated sample import. Raw provider exports are not retained. "
                f"Consent reference: {self.consent_reference}"
            ),
            metrics=metrics,
        )
