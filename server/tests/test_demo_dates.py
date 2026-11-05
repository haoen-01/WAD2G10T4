"""The demo's synthetic readings end on today when `demo_dates_follow_today` is on: the same values,
every day moved by one offset, the programmes with them, and nothing real or earlier rewritten."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop import seed, supabase_smoke
from silverloop.adapters.synthetic import SyntheticFixtureAdapter
from silverloop.config import Settings
from silverloop.context import ContextEvidence, ExternalContext
from silverloop.db_models import (
    ActivityCandidateRow,
    DailyMetricRow,
    DecisionEvidenceRow,
    ProgrammeRow,
    ScenarioRunRow,
)
from silverloop.fixtures import (
    DEMO_ANCHOR_DAY,
    DEMO_PERSON_ID,
    DEMO_PERSONAS,
    synthetic_activity_candidates,
    synthetic_programmes,
)
from silverloop.local_time import local_date
from silverloop.main import create_app
from silverloop.models import ContextSignal
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import audit_events

# 3 pm in Singapore: the fixture's midday-UTC stamp (8 pm local) is still to come.
NOW = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)


def _repository(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> SqlAlchemyRepository:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        llm_enabled=False,
        **overrides,
    )
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    repository.create_schema_for_tests()
    return repository


def _rows(
    repository: SqlAlchemyRepository, person_id: str = DEMO_PERSON_ID
) -> list[DailyMetricRow]:
    with repository.sessions() as session:
        return list(
            session.scalars(
                select(DailyMetricRow)
                .where(DailyMetricRow.person_id == person_id)
                .order_by(DailyMetricRow.run_id, DailyMetricRow.day)
            )
        )


def test_the_readings_end_on_today_with_the_same_values_in_the_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    state = repository.reset().state
    today = local_date(NOW)
    assert state.current_day == today

    fixture = SyntheticFixtureAdapter(2026).read().metrics
    rows = _rows(repository)
    assert [row.steps for row in rows] == [metric.steps for metric in fixture]
    # One offset for every day: the gaps between days are the fixture's own.
    offset = today - DEMO_ANCHOR_DAY
    assert [row.day for row in rows] == [metric.day + offset for metric in fixture]
    # Still sample data, and never stamped later than the moment it was written.
    assert {row.source for row in rows} == {"synthetic"}
    assert {row.fixture_classification for row in rows} == {"synthetic_fixture"}
    assert max(row.observed_at.replace(tzinfo=UTC) for row in rows) <= NOW


def test_the_programmes_move_with_the_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    repository.reset()
    offset = local_date(NOW) - DEMO_ANCHOR_DAY
    with repository.sessions() as session:
        stored = {row.programme_id: row for row in session.scalars(select(ProgrammeRow))}
    for programme in synthetic_programmes():
        row = stored[programme.programme_id]
        assert row.next_session.replace(tzinfo=UTC) == programme.next_session + offset
        assert row.valid_until.replace(tzinfo=UTC) == programme.next_session + offset + timedelta(
            days=7
        )


def test_an_explicit_end_day_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    two_days_ago = local_date(NOW) - timedelta(days=2)
    assert repository.reset(end_on=two_days_ago).state.current_day == two_days_ago


def test_with_the_setting_off_the_fixture_keeps_its_own_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=False)
    assert repository.reset().state.current_day == DEMO_ANCHOR_DAY == date(2026, 8, 18)


def test_a_reset_never_rewrites_an_earlier_run_or_anyone_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reset writes a new run from the synthetic fixture; the readings already stored (an earlier
    run, or another person's) keep their own days."""
    repository = _repository(monkeypatch, demo_dates_follow_today=False)
    repository.reset()
    repository.reset(person_id="mr-tan")
    before_lim = [(row.run_id, row.day, row.steps) for row in _rows(repository)]
    before_tan = [(row.day, row.steps) for row in _rows(repository, "mr-tan")]

    repository.reset(end_on=local_date(NOW))

    after_lim = [(row.run_id, row.day, row.steps) for row in _rows(repository)]
    assert set(before_lim) <= set(after_lim)  # the August run is still there, untouched
    assert [(row.day, row.steps) for row in _rows(repository, "mr-tan")] == before_tan


# ── The default, and who can never follow today ───────────────────────────────


def test_the_setting_is_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # The suite pins it off in `conftest.py`; the shipped default is on.
    monkeypatch.delenv("DEMO_DATES_FOLLOW_TODAY", raising=False)
    assert Settings(_env_file=None).demo_dates_follow_today is True


def test_a_repository_built_without_settings_keeps_the_anchor_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The YAML scenarios (and the Supabase smoke) build their repository without settings.
    Their days stay pinned, even after the repository has resolved the process defaults for the
    planner and even if the environment turns the setting on."""
    monkeypatch.setenv("DEMO_DATES_FOLLOW_TODAY", "true")
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    assert repository.reset().state.current_day == DEMO_ANCHOR_DAY
    repository.advance("activity_declines", "pinned-1")
    assert repository.settings is not None  # the lazily resolved defaults are now loaded
    assert repository.reset().state.current_day == DEMO_ANCHOR_DAY


def test_the_demo_reset_route_ends_the_readings_on_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'demo.db').as_posix()}",
        silverloop_runtime_profile="offline",
        adapter_mode="fixture",
        llm_enabled=False,
        auth_enabled=False,
        demo_dates_follow_today=True,
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/v1/demo/reset")
        assert response.status_code == 200, response.text
        assert response.json()["state"]["current_day"] == local_date(NOW).isoformat()
        state = client.get(f"/v1/people/{DEMO_PERSON_ID}/state")
        assert state.json()["current_day"] == local_date(NOW).isoformat()


# ── The Singapore day, not the UTC one ────────────────────────────────────────


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # 00:30 on Thu 5 Nov in Singapore, still Wed 4 Nov in UTC.
        (datetime(2026, 11, 4, 16, 30, tzinfo=UTC), date(2026, 11, 5)),
        # 23:59 on Wed 4 Nov in Singapore.
        (datetime(2026, 11, 4, 15, 59, tzinfo=UTC), date(2026, 11, 4)),
    ],
)
def test_today_is_the_day_in_singapore(
    monkeypatch: pytest.MonkeyPatch, moment: datetime, expected: date
) -> None:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: moment)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        llm_enabled=False,
        demo_dates_follow_today=True,
    )
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    repository.create_schema_for_tests()
    assert repository.reset().state.current_day == expected
    rows = _rows(repository)
    assert rows[-1].day == expected
    # The latest reading's midday-UTC stamp would be in the future; it is held at the moment.
    assert max(row.observed_at.replace(tzinfo=UTC) for row in rows) <= moment


# ── Everything date-bound moves together ──────────────────────────────────────


def test_the_baseline_and_the_decisions_are_the_same_as_on_the_anchor_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the dates move: the baseline, its window and what the policy decides are unchanged."""
    pinned = _repository(monkeypatch, demo_dates_follow_today=False)
    moved = _repository(monkeypatch, demo_dates_follow_today=True)
    assert pinned.reset().state.baseline == moved.reset().state.baseline
    events = ["activity_declines", "activity_declines", "recovery", "low_wear"]
    for index, event in enumerate(events):
        a = pinned.advance(event, f"same-{index}").state
        b = moved.advance(event, f"same-{index}").state
        assert a.last_decision == b.last_decision
        assert a.decided_by_gate == b.decided_by_gate
        assert a.baseline == b.baseline
        assert b.current_day - a.current_day == local_date(NOW) - DEMO_ANCHOR_DAY


def test_the_activity_listings_follow_the_new_day(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    today = repository.reset().state.current_day
    expected = {
        candidate.activity_id: candidate.start_at
        for candidate in synthetic_activity_candidates(today)
        if candidate.start_at is not None
    }
    with repository.sessions() as session:
        stored = {
            row.activity_id: row.start_at.replace(tzinfo=UTC)
            for row in session.scalars(select(ActivityCandidateRow))
            if row.start_at is not None
        }
    assert stored == expected
    assert min(local_date(start) for start in stored.values()) >= today


def test_a_reset_on_the_anchor_day_after_one_on_today_moves_the_programmes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No mix of November programmes and August readings after the setting is switched off."""
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    repository.reset()
    repository.reset(end_on=DEMO_ANCHOR_DAY)
    with repository.sessions() as session:
        stored = {row.programme_id: row for row in session.scalars(select(ProgrammeRow))}
    for programme in synthetic_programmes():
        assert stored[programme.programme_id].next_session.replace(tzinfo=UTC) == (
            programme.next_session
        )


@dataclass
class _RecordingProvider:
    """A stand-in for `ExternalContextProvider` that records which day it was asked about."""

    signal: ContextSignal
    evidence: list[ContextEvidence]
    asked: list[datetime] = field(default_factory=list)

    def fetch(self, as_of: datetime) -> ExternalContext:
        self.asked.append(as_of)
        return ExternalContext(signal=self.signal, evidence=self.evidence)


def _live_rain() -> _RecordingProvider:
    return _RecordingProvider(
        signal=ContextSignal(
            rainy=True,
            note="Live rainfall gauge reading high.",
            weather_source="live",
            weather_valid_until=NOW + timedelta(minutes=30),
        ),
        evidence=[
            ContextEvidence(
                source="nea_weather_live",
                observed_at=NOW,
                expires_at=NOW + timedelta(minutes=30),
                confidence=0.9,
                evidence_id="E-TEST-LIVE-RAIN",
                payload={"available": True},
            )
        ],
    )


def _repository_with(
    monkeypatch: pytest.MonkeyPatch, provider: _RecordingProvider
) -> SqlAlchemyRepository:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        llm_enabled=False,
        demo_dates_follow_today=True,
    )
    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:", settings=settings, context_provider=provider
    )
    repository.create_schema_for_tests()
    return repository


def test_live_weather_speaks_for_the_simulated_day_once_it_is_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live weather is only ever about today in Singapore. A demo whose readings end yesterday
    advances onto today, so the live reading is used for that day: rain explains the decline."""
    provider = _live_rain()
    repository = _repository_with(monkeypatch, provider)
    today = local_date(NOW)
    repository.reset(end_on=today - timedelta(days=1))

    state = repository.advance("activity_declines", "live-today-1").state

    assert state.current_day == today
    assert state.signal.context.weather_source == "live"
    assert state.signal.context.rainy is True
    assert state.last_decision.value == "no_action"
    # The holiday lookup was asked about the moved day, not about August.
    assert [local_date(asked) for asked in provider.asked] == [today]


def test_after_a_reset_on_today_the_next_simulated_day_keeps_simulated_weather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reset ends the readings on today, so the next simulated day is tomorrow: today's live
    rain is recorded as not about that day and never stamped onto it."""
    provider = _live_rain()
    repository = _repository_with(monkeypatch, provider)
    repository.reset()

    state = repository.advance("activity_declines", "tomorrow-1").state

    assert state.current_day == local_date(NOW) + timedelta(days=1)
    context = state.signal.context
    assert (context.rainy, context.weather_source, context.note) == (False, "simulated", None)
    assert [local_date(asked) for asked in provider.asked] == [state.current_day]
    detail = next(
        event.detail
        for event in audit_events(repository, person_id=DEMO_PERSON_ID)
        if "external_context_evidence" in event.detail
    )
    assert detail["expired_context_evidence"][0]["reason"] == "not_about_this_day"
    # Idempotent per event id, as before.
    again = repository.advance("activity_declines", "tomorrow-1").state
    assert again.current_day == state.current_day


# ── When a reading was observed ───────────────────────────────────────────────


def test_a_pinned_read_keeps_the_fixtures_own_stamps_whatever_the_clock() -> None:
    """Without `end_on` nothing moves, and the real clock is never consulted: even a `now` before
    the anchor day's midday leaves every midday-UTC stamp as it is."""
    before_anchor_noon = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)
    pinned = SyntheticFixtureAdapter(2026).read(now=before_anchor_noon).metrics
    assert [metric.observed_at for metric in pinned] == [
        datetime.combine(metric.day, datetime.min.time().replace(hour=12), tzinfo=UTC)
        for metric in pinned
    ]
    assert [m.observed_at for m in pinned] == [
        m.observed_at for m in SyntheticFixtureAdapter(2026).read().metrics
    ]


def _latest(repository: SqlAlchemyRepository) -> tuple[DailyMetricRow, DecisionEvidenceRow]:
    with repository.sessions() as session:
        metric = session.scalars(
            select(DailyMetricRow)
            .where(DailyMetricRow.person_id == DEMO_PERSON_ID)
            .order_by(DailyMetricRow.recorded_at.desc(), DailyMetricRow.day.desc())
        ).first()
        decision = session.scalars(
            select(DecisionEvidenceRow).order_by(DecisionEvidenceRow.recorded_at.desc())
        ).first()
    assert metric is not None and decision is not None
    return metric, decision


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # 3 pm in Singapore: midday UTC (8 pm) is still to come, so the stamp is held at now.
        (NOW, NOW),
        # 1 am in Singapore, still the day before in UTC: held at the day's own midnight UTC, so
        # the evidence's UTC date (which the contact cap reads) is still the day it is about.
        (
            datetime(2026, 11, 3, 17, 0, tzinfo=UTC),
            datetime(2026, 11, 4, 0, 0, tzinfo=UTC),
        ),
        # 9 pm in Singapore: midday UTC has passed, so the fixture's own stamp stands.
        (
            datetime(2026, 11, 4, 13, 0, tzinfo=UTC),
            datetime(2026, 11, 4, 12, 0, tzinfo=UTC),
        ),
    ],
)
def test_a_day_advanced_onto_today_is_never_stamped_in_its_future(
    monkeypatch: pytest.MonkeyPatch, moment: datetime, expected: datetime
) -> None:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: moment)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        llm_enabled=False,
        demo_dates_follow_today=True,
    )
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    repository.create_schema_for_tests()
    today = local_date(moment)
    repository.reset(end_on=today - timedelta(days=1))

    state = repository.advance("activity_declines", "onto-today").state

    assert state.current_day == today
    metric, decision = _latest(repository)
    assert metric.day == today
    assert metric.observed_at.replace(tzinfo=UTC) == expected
    assert decision.observed_at.replace(tzinfo=UTC) == expected
    assert decision.observed_at.date() == today


def test_a_simulated_day_after_today_and_a_past_day_keep_midday_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moved = _repository(monkeypatch, demo_dates_follow_today=True)
    moved.reset()  # ends on today, so the next day is tomorrow
    moved.advance("activity_declines", "tomorrow")
    tomorrow = local_date(NOW) + timedelta(days=1)
    metric, decision = _latest(moved)
    noon = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 12, tzinfo=UTC)
    assert (metric.day, metric.observed_at.replace(tzinfo=UTC)) == (tomorrow, noon)
    assert decision.observed_at.replace(tzinfo=UTC) == noon

    pinned = _repository(monkeypatch, demo_dates_follow_today=False)
    pinned.reset()
    pinned.advance("activity_declines", "august")
    metric, _ = _latest(pinned)
    assert metric.observed_at.replace(tzinfo=UTC) == datetime(2026, 8, 19, 12, tzinfo=UTC)


# ── The other commands that reset ─────────────────────────────────────────────


def _command_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'command.db').as_posix()}",
        silverloop_runtime_profile="offline",
        adapter_mode="fixture",
        llm_enabled=False,
        **overrides,
    )


def _prepared(settings: Settings) -> None:
    schema = SqlAlchemyRepository(settings.database_url)
    schema.create_schema_for_tests()
    schema.close()


def test_pnpm_seed_ends_every_persona_on_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    settings = _command_settings(tmp_path, demo_dates_follow_today=True)
    _prepared(settings)
    monkeypatch.setattr(seed, "get_settings", lambda: settings)
    monkeypatch.setattr(seed, "upgrade_database", lambda _url: None)

    seed.main()

    check = SqlAlchemyRepository(settings.database_url)
    with check.sessions() as session:
        days = {
            run.person_id: run.current_day
            for run in session.scalars(
                select(ScenarioRunRow).where(ScenarioRunRow.active.is_(True))
            )
        }
    check.close()
    assert set(days) == set(DEMO_PERSONAS)
    assert set(days.values()) == {local_date(NOW)}


@pytest.mark.parametrize("follow_today", [True, False])
def test_the_supabase_smoke_writes_the_same_days_the_api_would(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, follow_today: bool
) -> None:
    """The smoke resets Mdm Lim and rewrites the shared programme rows. Built with the app's
    settings, it writes the days the API's own reset would, so it never pulls the programmes back
    to August under every other run (or forward, with the setting off). Postgres-only steps are
    stood in for; the reset, advance and outcome are the real ones, on SQLite."""
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    settings = _command_settings(tmp_path, demo_dates_follow_today=follow_today)
    _prepared(settings)
    monkeypatch.setattr(supabase_smoke, "validate_runtime", lambda _settings: None)
    monkeypatch.setattr(supabase_smoke, "upgrade_database", lambda _url: None)
    monkeypatch.setattr(supabase_smoke, "apply_rls_posture", lambda _url: None)
    real_readiness = SqlAlchemyRepository.readiness
    monkeypatch.setattr(
        SqlAlchemyRepository,
        "readiness",
        lambda self, profile: real_readiness(self, profile).model_copy(
            update={"status": "ready", "tables_without_rls": []}
        ),
    )

    assert supabase_smoke.run(settings)["status"] == "ok"

    end_on = local_date(NOW) if follow_today else DEMO_ANCHOR_DAY
    check = SqlAlchemyRepository(settings.database_url)
    with check.sessions() as session:
        run = session.scalars(
            select(ScenarioRunRow).where(
                ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == DEMO_PERSON_ID
            )
        ).one()
        stored = {row.programme_id: row for row in session.scalars(select(ProgrammeRow))}
    check.close()
    # One smoke day after the reset.
    assert run.current_day == end_on + timedelta(days=1)
    for programme in synthetic_programmes(end_on - DEMO_ANCHOR_DAY):
        assert stored[programme.programme_id].next_session.replace(tzinfo=UTC) == (
            programme.next_session
        )
