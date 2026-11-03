"""New simulator events: `rain_clears_activity_low` and `public_holiday`.

See `scenarios/12_rain_then_persistent.yaml` and `scenarios/13_public_holiday.yaml` for the
end-to-end decision-ladder assertions; these tests pin down the context/quality shape each event
produces directly against the repository.
"""

from __future__ import annotations

import pytest

from silverloop.sql_repository import SqlAlchemyRepository


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()
    return instance


def test_rain_clears_activity_low_turns_off_the_rain_flag(repo: SqlAlchemyRepository) -> None:
    response = repo.advance("rain_clears_activity_low", event_id="clear-1")

    assert response.state.signal.context.rainy is False


def test_rain_clears_activity_low_escalates_past_a_rain_explained_dip(
    repo: SqlAlchemyRepository,
) -> None:
    """The day after `rain_explains_decline` (`NO_ACTION`, sustained_low_days < 2), activity that
    stays low with `rainy=False` must no longer be excused: the rain gate in `policy.py` only
    applies while `sustained_low_days < 2`, so the decision must escalate.
    """
    rain_day = repo.advance("rain_explains_decline", event_id="chain-1")
    assert rain_day.state.last_decision.value == "no_action"

    cleared_day = repo.advance("rain_clears_activity_low", event_id="chain-2")

    assert cleared_day.state.signal.context.rainy is False
    assert cleared_day.state.last_decision.value != "no_action"
    assert cleared_day.state.signal.sustained_low_days >= 2


def test_public_holiday_sets_the_holiday_context_flag(repo: SqlAlchemyRepository) -> None:
    response = repo.advance("public_holiday", event_id="holiday-1")

    assert response.state.signal.context.holiday is True
    assert response.state.signal.context.note is not None


def test_public_holiday_does_not_by_itself_suppress_the_policy_decision(
    repo: SqlAlchemyRepository,
) -> None:
    """`policy.py` never reads `context.holiday`; a holiday is explanatory context only and must
    never silently change what the deterministic ladder would otherwise decide for the same
    steps/wear-hours/severity.
    """
    response = repo.advance("public_holiday", event_id="holiday-2")

    assert response.state.signal.context.holiday is True
    # A ~25% single-day dip with sufficient wear-time and no persistence is a gentle nudge
    # regardless of the holiday flag -- holiday never earns a free NO_ACTION/suppress here.
    assert response.state.last_decision.value == "gentle_nudge"


def test_unsupported_event_name_still_rejected(repo: SqlAlchemyRepository) -> None:
    with pytest.raises(ValueError, match="Unsupported event"):
        repo.advance("not_a_real_event", event_id="bad-1")
