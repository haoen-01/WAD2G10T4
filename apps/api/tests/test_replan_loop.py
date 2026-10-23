"""Answering a replan offer: the loop R7 asks for, end to end.

The acceptance criteria, verbatim from `docs/audits/personalisation-v2/review-eval-sec.md` R7:
after `replace` the week has one entry for that day, the old row carries `replaced_reason="full"`,
`awaiting_report` is false for it, `plans_due` counts 1, and the audit has `replan_offered` +
`replanned`. Plus the sentence behind all of it: the senior is never asked "did you get a chance
to go?" about a session that was replaced.

Repository-level, with the HTTP routes checked alongside, because the person-scoping (404 rather
than an existence oracle) is the route's own contribution.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.db_models import ReplanOfferRow, WeekPlanEntryRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import ReplanReason, ReplanResolution
from silverloop.sql_repository import SqlAlchemyRepository

GARDENING = "activity-gardening-1"
GARDENING_DAY = date(2026, 8, 19)


def _offer(repository: SqlAlchemyRepository) -> ReplanOfferRow:
    with repository.sessions() as session:
        return session.scalars(select(ReplanOfferRow)).one()


def _plan_rows(repository: SqlAlchemyRepository) -> list[WeekPlanEntryRow]:
    with repository.sessions() as session:
        return list(
            session.scalars(select(WeekPlanEntryRow).order_by(WeekPlanEntryRow.plan_id)).all()
        )


def _search_everything(repository: SqlAlchemyRepository) -> list[str]:
    """An unconstrained search, so its results count as listings this run showed them."""
    response = repository.search_activities(
        text=None, intent=None, person_id=DEMO_PERSON_ID, actor="senior"
    )
    return [item.candidate.activity_id for item in response.results]


def _runs_on(repository: SqlAlchemyRepository, activity_id: str, day: date) -> bool:
    candidate = next(c for c in repository.list_activities() if c.activity_id == activity_id)
    return candidate.start_at is not None and local_date(candidate.start_at) == day


def _offered_plan(repository: SqlAlchemyRepository) -> tuple[str, str]:
    """Plan the gardening session, fill it up, and return `(plan_id, offered_alternative_id)`."""
    week = repository.plan_activity(GARDENING, GARDENING_DAY, "senior")
    plan_id = next(
        entry.plan_id for entry in week.entries if entry.activity.activity_id == GARDENING
    )
    repository.advance("programme_becomes_full", event_id="full-1")
    notices = repository.replan_notices()
    assert len(notices) == 1, "the fixture must produce exactly one offer to answer"
    assert notices[0].alternative is not None
    return plan_id, notices[0].alternative.candidate.activity_id


# ── Accepting ─────────────────────────────────────────────────────────────────────────────────


def test_replacing_leaves_one_live_entry_on_that_day(repository: SqlAlchemyRepository) -> None:
    plan_id, alternative_id = _offered_plan(repository)

    week = repository.replace_planned_activity(plan_id, alternative_id, "senior")

    on_that_day = [entry for entry in week.entries if entry.day == GARDENING_DAY]
    live = [entry for entry in on_that_day if entry.replaced_reason is None]
    assert len(live) == 1
    assert live[0].activity.activity_id == alternative_id
    # The old row is kept, not deleted: it is how the person's week says what happened.
    replaced = [entry for entry in on_that_day if entry.plan_id == plan_id]
    assert len(replaced) == 1
    assert replaced[0].replaced_reason == ReplanReason.FULL.value


def test_a_replaced_row_is_never_awaiting_a_report(repository: SqlAlchemyRepository) -> None:
    """The ask audit F finding 8 reproduced: "did you get a chance to go?" about a session that
    was fully booked."""
    plan_id, alternative_id = _offered_plan(repository)
    repository.replace_planned_activity(plan_id, alternative_id, "senior")

    # Past the planned day, which is when the home screen asks.
    repository.advance("recovery", event_id="recovery-1")
    repository.advance("recovery", event_id="recovery-2")

    week = repository.week_plan()
    replaced = next(entry for entry in week.entries if entry.plan_id == plan_id)
    assert replaced.awaiting_report is False
    assert replaced.replaced_reason == ReplanReason.FULL.value
    # ...and the replacement is asked about, exactly once.
    asked = [entry for entry in week.entries if entry.awaiting_report]
    assert [entry.activity.activity_id for entry in asked] == [alternative_id]


def test_a_replaced_row_cannot_be_reported_on_at_all(repository: SqlAlchemyRepository) -> None:
    plan_id, alternative_id = _offered_plan(repository)
    repository.replace_planned_activity(plan_id, alternative_id, "senior")
    repository.advance("recovery", event_id="recovery-1")
    repository.advance("recovery", event_id="recovery-2")

    with pytest.raises(ValueError, match="replaced"):
        repository.record_planned_follow_through(plan_id, "went", None, "senior")


def test_plans_due_counts_the_replacement_once_and_the_replaced_row_never(
    repository: SqlAlchemyRepository,
) -> None:
    plan_id, alternative_id = _offered_plan(repository)
    repository.replace_planned_activity(plan_id, alternative_id, "senior")
    repository.advance("recovery", event_id="recovery-1")
    repository.advance("recovery", event_id="recovery-2")

    metrics = repository.metrics()

    assert metrics.activities_planned == 2
    assert metrics.plans_due == 1


def test_the_audit_trail_carries_both_halves_of_the_loop(
    repository: SqlAlchemyRepository,
) -> None:
    plan_id, alternative_id = _offered_plan(repository)
    repository.replace_planned_activity(plan_id, alternative_id, "senior")

    types = [event.event_type for event in repository.list_events()]
    assert "replan_offered" in types
    assert "replanned" in types
    replanned = next(event for event in repository.list_events() if event.event_type == "replanned")
    assert replanned.detail["plan_id"] == plan_id
    assert replanned.detail["reason_code"] == ReplanReason.FULL.value
    assert replanned.detail["replacement_activity_id"] == alternative_id
    assert replanned.detail["took_offered_alternative"] is True


def test_accepting_closes_the_offer_and_the_notice_does_not_come_back(
    repository: SqlAlchemyRepository,
) -> None:
    plan_id, alternative_id = _offered_plan(repository)

    repository.replace_planned_activity(plan_id, alternative_id, "senior")

    assert _offer(repository).resolution == ReplanResolution.ACCEPTED.value
    assert repository.replan_notices() == []


def test_replacing_a_plan_nothing_has_happened_to_is_refused(
    repository: SqlAlchemyRepository,
) -> None:
    week = repository.plan_activity(GARDENING, GARDENING_DAY, "senior")
    plan_id = week.entries[0].plan_id

    with pytest.raises(ValueError, match="Nothing needs replacing"):
        repository.replace_planned_activity(plan_id, "activity-chair-mobility-1", "senior")


def test_replacing_with_a_listing_that_does_not_run_that_day_is_refused(
    repository: SqlAlchemyRepository,
) -> None:
    """The replacement goes in through the same path a plan from a search does, so it obeys the
    same session-day rule rather than getting a private exemption."""
    plan_id, _ = _offered_plan(repository)
    # Shown to them, so the rule under test here is the day and not the offer.
    _search_everything(repository)

    with pytest.raises(ValueError, match="not on the day chosen"):
        # activity-chair-mobility-2 runs on the 21st, not on the 19th.
        repository.replace_planned_activity(plan_id, "activity-chair-mobility-2", "senior")


def test_replacing_with_a_listing_that_was_never_offered_is_refused(
    repository: SqlAlchemyRepository,
) -> None:
    """Red team P2-12. `respond_to_activity` refuses to plan a listing this run never showed the
    person -- the filter encodes their own request, so a listing it removed is one they asked not
    to be offered. `replace` had no such check: any listing that could be planned on the day went
    straight onto the week, and for a listing with no fixed time "can be planned on that day" is
    vacuous, so `activity-reading-corner` -- never offered, never shown -- was accepted.
    """
    plan_id, _ = _offered_plan(repository)

    with pytest.raises(ValueError, match="not offered as a replacement"):
        repository.replace_planned_activity(plan_id, "activity-reading-corner", "senior")

    live = [entry for entry in _plan_rows(repository) if entry.replaced_reason is None]
    assert [entry.activity_id for entry in live] == [GARDENING], "nothing was put on their week"


def test_a_listing_this_run_showed_them_may_still_be_chosen(
    repository: SqlAlchemyRepository,
) -> None:
    """The gate is "was this offered to you", not "is this the one we picked": a person who
    searched and found something better may answer the offer with it."""
    plan_id, alternative_id = _offered_plan(repository)
    shown = _search_everything(repository)
    chosen = next(
        activity_id
        for activity_id in shown
        if activity_id not in {alternative_id, GARDENING}
        and _runs_on(repository, activity_id, GARDENING_DAY)
    )

    week = repository.replace_planned_activity(plan_id, chosen, "senior")

    assert any(entry.activity.activity_id == chosen for entry in week.entries)


def test_replacing_twice_is_refused(repository: SqlAlchemyRepository) -> None:
    plan_id, alternative_id = _offered_plan(repository)
    repository.replace_planned_activity(plan_id, alternative_id, "senior")

    with pytest.raises(ValueError, match="already been replaced"):
        repository.replace_planned_activity(plan_id, "activity-seated-strength-1", "senior")


# ── Declining ─────────────────────────────────────────────────────────────────────────────────


def test_declining_is_recorded_and_the_same_offer_is_not_put_again(
    repository: SqlAlchemyRepository,
) -> None:
    """The half that lived in browser state: `week-and-goals.tsx` kept a local `dismissed` set,
    so the notice came back on the next reload."""
    plan_id, _ = _offered_plan(repository)
    offer_id = _offer(repository).offer_id

    resolved = repository.decline_replan_offer(offer_id, "senior")

    assert resolved.resolution == ReplanResolution.DECLINED
    assert resolved.resolved_at is not None
    assert repository.replan_notices() == []
    # The plan itself is untouched: declining a replacement is not declining the outing.
    plan = next(row for row in _plan_rows(repository) if row.plan_id == plan_id)
    assert plan.replaced_reason is None
    assert "replan_declined" in [event.event_type for event in repository.list_events()]


def test_a_declined_offer_is_not_re_offered_on_the_next_simulated_day(
    repository: SqlAlchemyRepository,
) -> None:
    _offered_plan(repository)
    repository.decline_replan_offer(_offer(repository).offer_id, "senior")

    repository.advance("programme_becomes_full", event_id="full-2")

    assert repository.replan_notices() == []


def test_declining_twice_is_refused(repository: SqlAlchemyRepository) -> None:
    _offered_plan(repository)
    offer_id = _offer(repository).offer_id
    repository.decline_replan_offer(offer_id, "senior")

    with pytest.raises(ValueError, match="already been answered"):
        repository.decline_replan_offer(offer_id, "senior")


def test_an_offer_from_a_dead_run_cannot_be_answered(repository: SqlAlchemyRepository) -> None:
    _offered_plan(repository)
    offer_id = _offer(repository).offer_id

    repository.reset()

    with pytest.raises(KeyError):
        repository.decline_replan_offer(offer_id, "senior")


# ── Through the routes ────────────────────────────────────────────────────────────────────────


def test_the_routes_carry_the_loop_and_answer_404_for_what_is_not_this_persons(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    plan_id, alternative_id = _offered_plan(repository)
    offer_id = _offer(repository).offer_id

    missing_plan = client.post(
        "/v1/people/mdm-lim/week/plan_nope/replace", json={"activity_id": alternative_id}
    )
    assert missing_plan.status_code == 404
    missing_offer = client.post("/v1/people/mdm-lim/replan-offers/offer_nope/decline")
    assert missing_offer.status_code == 404

    replaced = client.post(
        f"/v1/people/mdm-lim/week/{plan_id}/replace", json={"activity_id": alternative_id}
    )
    assert replaced.status_code == 200
    days = [entry for entry in replaced.json()["entries"] if entry["day"] == "2026-08-19"]
    assert [entry["activity"]["activity_id"] for entry in days if not entry["replaced_reason"]] == [
        alternative_id
    ]

    declined = client.post(f"/v1/people/mdm-lim/replan-offers/{offer_id}/decline")
    assert declined.status_code == 422, "an accepted offer cannot also be declined"


def test_the_route_refuses_a_listing_that_was_never_offered_in_plain_words(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Refused, not silently ignored, and in a sentence a person could read."""
    plan_id, _ = _offered_plan(repository)

    response = client.post(
        f"/v1/people/mdm-lim/week/{plan_id}/replace",
        json={"activity_id": "activity-reading-corner"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "not offered as a replacement" in detail
    for word in ("shown", "filter", "query", "gate"):
        assert word not in detail


def test_declining_through_the_route_returns_the_resolved_offer(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _offered_plan(repository)
    offer_id = _offer(repository).offer_id

    response = client.post(f"/v1/people/mdm-lim/replan-offers/{offer_id}/decline")

    assert response.status_code == 200
    body = response.json()
    assert body["offer_id"] == offer_id
    assert body["resolution"] == ReplanResolution.DECLINED.value
    assert body["reason"] == ReplanReason.FULL.value
    assert client.get("/v1/people/mdm-lim/replan-notices").json() == []


# ── Counted, so the loop can be measured rather than asserted ─────────────────────────────────


def test_metrics_count_offers_and_both_answers(repository: SqlAlchemyRepository) -> None:
    """Audit F finding 8's last limb: no metric counted offers, accepts or declines, so the
    product's headline agentic moment could not be measured at all."""
    plan_id, alternative_id = _offered_plan(repository)
    assert repository.metrics().replans_offered == 1
    assert repository.metrics().replans_accepted == 0

    repository.replace_planned_activity(plan_id, alternative_id, "senior")

    after_accept = repository.metrics()
    assert after_accept.replans_offered == 1
    assert after_accept.replans_accepted == 1
    assert after_accept.replans_declined == 0


def test_metrics_count_a_decline_without_counting_it_as_an_accept(
    repository: SqlAlchemyRepository,
) -> None:
    _offered_plan(repository)

    repository.decline_replan_offer(_offer(repository).offer_id, "senior")

    metrics = repository.metrics()
    assert metrics.replans_offered == 1
    assert metrics.replans_declined == 1
    assert metrics.replans_accepted == 0
