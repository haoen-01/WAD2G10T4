from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from silverloop.adapters.models import CanonicalDailyMetric, SourceClassification


class AdapterBatch(BaseModel):
    source: str
    source_classification: SourceClassification
    disclosure: str
    metrics: list[CanonicalDailyMetric]


class DailyMetricsAdapter(Protocol):
    """Detachable boundary for provider data normalised to canonical daily metrics."""

    def read(self) -> AdapterBatch: ...
