"""Wiring for the optional live context provider (`silverloop.context`):

- config default is off, and the offline runtime profile force-disables it regardless;
- when enabled, live context can only OR in additional true signals on top of the five scripted
  simulation events -- it must never override or race what the simulator already decided.

The 11 committed scenarios and the evaluation artifact never pass a context provider (see
`scenarios.py`), so this file is the only place that exercises the merge behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from silverloop.config import Settings
from silverloop.context import ContextEvidence, ExternalContext, ExternalContextProvider
from silverloop.main import create_app
from silverloop.models import ContextSignal
from silverloop.sql_repository import SqlAlchemyRepository

# ── Config default / offline force-disable ────────────────────────────────────


def test_external_context_is_disabled_by_default() -> None:
    assert Settings(database_url="sqlite+pysqlite:///:memory:").external_context_enabled is False


def test_create_app_builds_no_context_provider_when_disabled() -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
        external_context_enabled=False,
    )
    app = create_app(settings=settings, migrate_on_start=False)
    assert app.state.repository._context_provider is None  # type: ignore[attr-defined]


def test_create_app_force_disables_context_provider_under_offline_profile() -> None:
    """The offline demo and Playwright must work with no network -- even an operator who sets
    `EXTERNAL_CONTEXT_ENABLED=true` must not get live network calls under the offline profile.
    """
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
        external_context_enabled=True,
    )
    app = create_app(settings=settings, migrate_on_start=False)
    assert app.state.repository._context_provider is None  # type: ignore[attr-defined]


def test_create_app_builds_context_provider_when_enabled_and_not_offline() -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="shared",
        auth_enabled=False,
        external_context_enabled=True,
        external_context_country="SG",
        external_context_timeout_seconds=1.5,
    )
    app = create_app(settings=settings, migrate_on_start=False)
    provider = app.state.repository._context_provider  # type: ignore[attr-defined]
    assert isinstance(provider, ExternalContextProvider)
    assert provider._timeout == 1.5
    assert provider._country_code == "SG"


# ── Merge behaviour: supplements, never overrides or races the simulator ─────


@dataclass
class _FakeProvider:
    """A duck-typed stand-in for `ExternalContextProvider` -- avoids real network calls while
    testing the repository's merge logic in isolation.
    """

    signal: ContextSignal
    evidence: list[ContextEvidence]

    def fetch(self, as_of: datetime) -> ExternalContext:
        return ExternalContext(signal=self.signal, evidence=self.evidence)


def _fake_evidence(source: str) -> ContextEvidence:
    now = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
    return ContextEvidence(
        source=source,
        observed_at=now,
        expires_at=now,
        confidence=0.9,
        evidence_id=f"E-TEST-{source}",
        payload={"available": True},
    )


def _expired_evidence(source: str) -> ContextEvidence:
    """Evidence that has already expired by the time the default repository's next event
    (2026-08-19 12:00 UTC) is evaluated.
    """
    return ContextEvidence(
        source=source,
        observed_at=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        expires_at=datetime(2026, 8, 19, 6, 0, tzinfo=UTC),
        confidence=0.9,
        evidence_id=f"E-STALE-{source}",
        payload={"available": True},
    )


def test_live_rain_context_supplements_a_scripted_decline_like_the_rain_event() -> None:
    """A single-day decline with live rain detected must be treated the same way the scripted
    `rain_explains_decline` event is: `NO_ACTION`, not `GENTLE_NUDGE`.
    """
    provider = _FakeProvider(
        signal=ContextSignal(rainy=True, note="Live rainfall gauge reading high."),
        evidence=[_fake_evidence("nea_weather_live")],
    )
    repo = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", context_provider=provider)
    repo.create_schema_for_tests()
    repo.reset()

    response = repo.advance("activity_declines", event_id="live-rain-1")

    assert response.state.signal.context.rainy is True
    assert response.state.last_decision.value == "no_action"
    events = repo.list_events()
    detail = events[0].detail
    assert detail["external_context_evidence"] == [
        _fake_evidence("nea_weather_live").model_dump(mode="json")
    ]


def test_live_context_cannot_clear_a_scripted_true_signal() -> None:
    """Live context ORs in *additional* true signals; it must never race or override what the
    scripted `rain_explains_decline` event already set.
    """
    provider = _FakeProvider(
        signal=ContextSignal(rainy=False, holiday=False),  # live check disagrees
        evidence=[_fake_evidence("nea_weather_live")],
    )
    repo = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", context_provider=provider)
    repo.create_schema_for_tests()
    repo.reset()

    response = repo.advance("rain_explains_decline", event_id="scripted-rain-1")

    assert response.state.signal.context.rainy is True  # scripted signal still wins
    assert response.state.last_decision.value == "no_action"


def test_expired_context_evidence_does_not_contribute_a_true_signal() -> None:
    """A `ContextEvidence` whose `expires_at` has already passed by the time the day is
    evaluated is stale, not "checked and clear" -- it must not flip a context flag true, and the
    drop must be recorded in the audit detail rather than silently applied (see the programme
    freshness gate precedent).
    """
    provider = _FakeProvider(
        signal=ContextSignal(rainy=True, note="Live rainfall gauge reading high (stale)."),
        evidence=[_expired_evidence("nea_weather_live")],
    )
    repo = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", context_provider=provider)
    repo.create_schema_for_tests()
    repo.reset()

    response = repo.advance("recovery", event_id="stale-rain-1")

    assert response.state.signal.context.rainy is False
    events = repo.list_events()
    detail = events[0].detail
    assert detail["expired_context_evidence"] == [
        {
            "evidence_id": "E-STALE-nea_weather_live",
            "source": "nea_weather_live",
            "expires_at": "2026-08-19T06:00:00+00:00",
        }
    ]
    # Still recorded as fetched evidence, just not honoured in the merged context signal.
    assert detail["external_context_evidence"] == [
        _expired_evidence("nea_weather_live").model_dump(mode="json")
    ]


def test_no_context_provider_leaves_behaviour_unchanged() -> None:
    """Default construction (`context_provider=None`) must be a complete no-op: no evidence
    recorded, decisions unaffected -- exactly today's behaviour.
    """
    repo = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repo.create_schema_for_tests()
    repo.reset()

    response = repo.advance("activity_declines", event_id="no-provider-1")

    assert response.state.signal.context.rainy is False
    events = repo.list_events()
    assert events[0].detail["external_context_evidence"] == []
