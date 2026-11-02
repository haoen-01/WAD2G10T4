from __future__ import annotations

from typing import Protocol

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    AdvanceResponse,
    CandidatePreference,
    ConsentResponse,
    DailyMetric,
    DeclineReason,
    DemoResetResponse,
    Intervention,
    OperationalMetrics,
    OutcomeKind,
    OutcomeResponse,
    PersonState,
    ReadinessResponse,
    ReviewCase,
)


class SilverLoopRepository(Protocol):
    """Application-facing persistence boundary owned by FastAPI."""

    def ensure_active_run(self, *, person_id: str = DEMO_PERSON_ID) -> None: ...

    def reset(
        self, *, person_id: str = DEMO_PERSON_ID, allow_new_person: bool = False
    ) -> DemoResetResponse: ...

    def person_state(self, *, person_id: str = DEMO_PERSON_ID) -> PersonState: ...

    def daily_metrics(
        self, *, person_id: str = DEMO_PERSON_ID, days: int = 14
    ) -> list[DailyMetric]: ...

    def advance(
        self,
        event_name: str,
        event_id: str | None = None,
        *,
        person_id: str = DEMO_PERSON_ID,
    ) -> AdvanceResponse: ...

    def list_interventions(self, *, person_id: str = DEMO_PERSON_ID) -> list[Intervention]: ...

    def record_outcome(
        self,
        intervention_id: str,
        outcome: OutcomeKind | str,
        actor: str,
        *,
        reason: DeclineReason | str | None = None,
        person_id: str | None = None,
    ) -> OutcomeResponse: ...

    def list_candidate_preferences(
        self, *, person_id: str = DEMO_PERSON_ID
    ) -> list[CandidatePreference]: ...

    def set_consent(
        self, active: bool, reason: str, actor: str, *, person_id: str = DEMO_PERSON_ID
    ) -> ConsentResponse: ...

    def list_cases(self, *, person_id: str | None = None) -> list[ReviewCase]: ...

    def metrics(self, *, person_id: str = DEMO_PERSON_ID) -> OperationalMetrics: ...

    def readiness(self, runtime_profile: str) -> ReadinessResponse: ...

    def lookup_person_for_sub(self, sub: str) -> str | None: ...

    def upsert_person_link(self, sub: str, person_id: str, created_by: str) -> None: ...
