"""The review-setting receipt and review lessons (docs/calibration-trust-spec.md, section C).

- `build_receipt` picks its subject and places every review exactly once: counted toward loosening,
  asked sooner, or excluded with one reason;
- its counted set equals what the calibrator counts (`_threshold_episode_context` +
  `fixed_rule_output`) on the guided `mdm-wong` sequence and over generated histories;
- every review response carries the lesson `classify_review` gives its stored row;
- lesson and receipt text carry no note and no activity figure, pass the coordinator wording rules,
  and nothing new reaches the senior's screens or the calibration agent's tool payloads;
- a context-gap category changes no decision, proposal or review-setting row.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from silverloop.agent.guardrails import coordinator_text_violations
from silverloop.config import Settings
from silverloop.db_models import (
    CaseReviewRow,
    DecisionEvidenceRow,
    ReviewCaseRow,
    ReviewThresholdDecisionRow,
    ReviewThresholdProposalRow,
    ScenarioRunRow,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    CaseStatus,
    ContextGapCategory,
    HumanAction,
    OverrideReason,
    ReviewLessonReason,
    ReviewReceiptExclusion,
    ReviewReceiptStatus,
    ReviewSettingReceipt,
    ReviewThresholdProposer,
)
from silverloop.review_lessons import (
    LESSON_SUMMARIES,
    RECEIPT_RULE,
    ReceiptDecision,
    ReceiptDirection,
    ReceiptProposal,
    ReceiptReview,
    build_receipt,
    classify_review,
)
from silverloop.review_threshold import (
    FIXED_RULE_FALSE_ALARMS,
    FIXED_RULE_WINDOW_DAYS,
    FalseAlarmRef,
    ReviewThreshold,
    ReviewThresholdDecisionKind,
    ThresholdDecisionFact,
    fixed_rule_output,
)
from silverloop.sql_repository import SqlAlchemyRepository, _utcnow
from tests.test_review_threshold_demo import (
    CHAPTER_1,
    CHAPTER_2,
    CHAPTER_3,
    CHAPTER_4,
    DEMO_NOTE,
    PERSON,
    THRESHOLD,
    _open_case,
    _play,
    _review,
    _state,
)

_OFFLINE = dict(
    app_env="test",
    database_url="sqlite+pysqlite:///:memory:",
    silverloop_runtime_profile="offline",
    auth_enabled=False,
    llm_enabled=False,
)
TODAY = date(2026, 8, 20)
T0 = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
COUNTED = ReviewReceiptStatus.COUNTED_TOWARD_LOOSENING


# ── Pure: `build_receipt` ─────────────────────────────────────────────────────────────────────


def _receipt_review(
    review_id: str,
    *,
    opened_day: date | None,
    minutes: int,
    reason: ReviewLessonReason = ReviewLessonReason.NOT_A_CONCERN,
) -> ReceiptReview:
    kwargs: dict[str, Any] = {
        "status": CaseStatus.RESOLVED,
        "reviewer": "coordinator",
        "human_action": HumanAction.OVERRIDE,
        "override_reason": OverrideReason.NOT_A_CONCERN,
        "reached_too_late": False,
    }
    if reason == ReviewLessonReason.REACHED_TOO_LATE:
        kwargs.update(human_action=HumanAction.AGREE, override_reason=None, reached_too_late=True)
    elif reason == ReviewLessonReason.KNOWN_CONTEXT:
        kwargs.update(override_reason=OverrideReason.KNOWN_CONTEXT)
    elif reason == ReviewLessonReason.NOT_RESOLVED:
        kwargs.update(status=CaseStatus.ACKNOWLEDGED)
    lesson = classify_review(review_id=review_id, **kwargs)
    assert lesson.reason == reason
    return ReceiptReview(
        review_id=review_id,
        case_id=f"case_{review_id}",
        opened_day=opened_day,
        recorded_at=T0 + timedelta(minutes=minutes),
        lesson=lesson,
    )


def _proposal(
    proposal_id: str,
    *,
    minutes: int,
    is_open: bool = False,
    day: date = TODAY,
    cited: tuple[str, ...] = (),
    triggers: tuple[str, ...] = (),
    direction: ReceiptDirection = "looser",
    proposer: ReviewThresholdProposer = ReviewThresholdProposer.FIXED_RULE,
) -> ReceiptProposal:
    return ReceiptProposal(
        proposal_id=proposal_id,
        is_open=is_open,
        proposed_on_day=day,
        proposed_at=T0 + timedelta(minutes=minutes),
        cited_evidence_ids=cited,
        trigger_review_ids=triggers,
        direction=direction,
        proposer=proposer,
    )


def _approval(
    decision_id: str, *, minutes: int, effective: date, proposal_id: str | None
) -> ThresholdDecisionFact:
    return ThresholdDecisionFact(
        decision_id=decision_id,
        kind=ReviewThresholdDecisionKind.APPROVED,
        previous=ReviewThreshold(40, 3),
        after=ReviewThreshold(40, 4),
        decided_on_day=effective - timedelta(days=1),
        effective_from_day=effective,
        decided_at=T0 + timedelta(minutes=minutes),
        proposal_id=proposal_id,
    )


def _standing(receipt: ReviewSettingReceipt) -> dict[str, tuple[str, str | None]]:
    return {
        entry.review_id: (
            entry.status.value,
            entry.exclusion.value if entry.exclusion else None,
        )
        for entry in receipt.entries
    }


def test_every_review_is_placed_once_with_the_first_reason_that_applies() -> None:
    counted_from = TODAY - timedelta(days=10)
    window_start = TODAY - timedelta(days=FIXED_RULE_WINDOW_DAYS - 1)
    reviews = [
        _receipt_review("counted", opened_day=TODAY - timedelta(days=2), minutes=1),
        _receipt_review("on_counted_from", opened_day=counted_from, minutes=2),
        _receipt_review("before_setting", opened_day=counted_from - timedelta(days=1), minutes=3),
        _receipt_review("no_day", opened_day=None, minutes=4),
        _receipt_review(
            "late", opened_day=None, minutes=5, reason=ReviewLessonReason.REACHED_TOO_LATE
        ),
        _receipt_review(
            "context", opened_day=TODAY, minutes=6, reason=ReviewLessonReason.KNOWN_CONTEXT
        ),
        _receipt_review(
            "unresolved", opened_day=TODAY, minutes=7, reason=ReviewLessonReason.NOT_RESOLVED
        ),
        # Recorded after the next proposal would be made: only a proposal subject excludes it.
        _receipt_review("latest", opened_day=TODAY, minutes=90),
    ]
    facts = [_approval("approval", minutes=-5, effective=counted_from, proposal_id=None)]
    receipt = build_receipt(reviews=reviews, proposals=[], facts=facts, decisions=[], today=TODAY)

    assert receipt.subject == "next_proposal"
    assert receipt.proposal_id is None
    assert (receipt.as_of_day, receipt.counted_from_day) == (TODAY, counted_from)
    assert receipt.window_start_day == window_start
    assert receipt.needed == FIXED_RULE_FALSE_ALARMS
    assert _standing(receipt) == {
        "latest": ("counted_toward_loosening", None),
        "unresolved": ("excluded", "not_eligible_to_loosen"),
        "context": ("excluded", "not_eligible_to_loosen"),
        "late": ("asked_sooner", None),
        "no_day": ("excluded", "no_opening_day"),
        "before_setting": ("excluded", "before_current_setting"),
        "on_counted_from": ("counted_toward_loosening", None),
        "counted": ("counted_toward_loosening", None),
    }
    assert receipt.counted == 3
    # Most recent first, like the threshold history.
    assert [entry.review_id for entry in receipt.entries][0] == "latest"
    assert [entry.recorded_at for entry in receipt.entries] == sorted(
        (entry.recorded_at for entry in receipt.entries), reverse=True
    )
    assert not any(entry.cited for entry in receipt.entries)


def test_the_window_is_inclusive_at_both_ends() -> None:
    window_start = TODAY - timedelta(days=FIXED_RULE_WINDOW_DAYS - 1)
    reviews = [
        _receipt_review("first_day", opened_day=window_start, minutes=1),
        _receipt_review("day_before", opened_day=window_start - timedelta(days=1), minutes=2),
        _receipt_review("today", opened_day=TODAY, minutes=3),
        _receipt_review("tomorrow", opened_day=TODAY + timedelta(days=1), minutes=4),
    ]
    receipt = build_receipt(reviews=reviews, proposals=[], facts=[], decisions=[], today=TODAY)
    assert receipt.counted_from_day is None
    assert _standing(receipt) == {
        "first_day": ("counted_toward_loosening", None),
        "day_before": ("excluded", "outside_window"),
        "today": ("counted_toward_loosening", None),
        "tomorrow": ("excluded", "outside_window"),
    }


def test_an_open_proposal_is_the_subject_as_of_the_day_it_was_proposed() -> None:
    proposed_on = TODAY - timedelta(days=3)
    reviews = [
        _receipt_review("one", opened_day=proposed_on - timedelta(days=5), minutes=1),
        _receipt_review("two", opened_day=proposed_on, minutes=2),
        # Recorded after the proposal: excluded before anything else is asked of it.
        _receipt_review(
            "late_after", opened_day=None, minutes=20, reason=ReviewLessonReason.REACHED_TOO_LATE
        ),
        # In the window as of today but not as of the proposal's day.
        _receipt_review("after", opened_day=TODAY, minutes=30),
    ]
    proposals = [
        _proposal("older", minutes=0, day=proposed_on, triggers=("one",)),
        _proposal(
            "open",
            minutes=10,
            is_open=True,
            day=proposed_on,
            cited=("two", "one", "case_evidence"),
            triggers=("two",),
        ),
        _proposal("retry", minutes=11, day=proposed_on, triggers=("two",)),
        # A live approval exists, but the open proposal wins.
        _proposal("live", minutes=-100, day=proposed_on - timedelta(days=20)),
    ]
    facts = [
        _approval(
            "approval", minutes=-90, effective=proposed_on - timedelta(days=19), proposal_id="live"
        ),
        # Decided after the proposal: the calibrator never saw it, so it moves no counting.
        _approval("later", minutes=15, effective=proposed_on, proposal_id=None),
    ]
    decisions = [
        ReceiptDecision(
            "revert_b", decided_at=T0 + timedelta(minutes=22), trigger_review_id="late_after"
        ),
        ReceiptDecision(
            "revert_a", decided_at=T0 + timedelta(minutes=21), trigger_review_id="late_after"
        ),
    ]
    receipt = build_receipt(
        reviews=reviews, proposals=proposals, facts=facts, decisions=decisions, today=TODAY
    )

    assert (receipt.subject, receipt.proposal_id) == ("open_proposal", "open")
    assert receipt.as_of_day == proposed_on
    assert receipt.counted_from_day == proposed_on - timedelta(days=19)
    assert receipt.window_start_day == proposed_on - timedelta(days=FIXED_RULE_WINDOW_DAYS - 1)
    assert _standing(receipt) == {
        "after": ("excluded", "after_proposal"),
        "late_after": ("excluded", "after_proposal"),
        "two": ("counted_toward_loosening", None),
        "one": ("counted_toward_loosening", None),
    }
    assert receipt.counted == 2
    by_id = {entry.review_id: entry for entry in receipt.entries}
    # Cited means the proposal's stored evidence ids name the review itself.
    assert {rid for rid, entry in by_id.items() if entry.cited} == {"one", "two"}
    # The earliest output and decision a review triggered.
    assert by_id["one"].led_to_proposal_id == "older"
    assert by_id["two"].led_to_proposal_id == "open"
    assert by_id["late_after"].led_to_decision_id == "revert_a"
    assert by_id["after"].led_to_proposal_id is None


def test_the_live_approval_s_proposal_is_the_subject_without_an_open_one() -> None:
    proposed_on = TODAY - timedelta(days=5)
    reviews = [_receipt_review("one", opened_day=proposed_on, minutes=1)]
    proposals = [_proposal("behind_live", minutes=5, day=proposed_on, cited=("one",))]
    facts = [
        _approval(
            "approval",
            minutes=6,
            effective=proposed_on + timedelta(days=1),
            proposal_id="behind_live",
        )
    ]
    receipt = build_receipt(
        reviews=reviews, proposals=proposals, facts=facts, decisions=[], today=TODAY
    )
    assert (receipt.subject, receipt.proposal_id) == ("live_setting", "behind_live")
    assert receipt.as_of_day == proposed_on
    assert receipt.counted_from_day is None
    assert receipt.counted == 1
    assert receipt.entries[0].cited is True

    # The approval was already made today, effective from tomorrow: not yet live by
    # `resolve_live_threshold`, but its proposal is still the subject, not a fresh next-proposal
    # window -- the review already fed it, and re-counting it against an unmade proposal would
    # show it as counted twice.
    pending = build_receipt(
        reviews=reviews,
        proposals=proposals,
        facts=facts,
        decisions=[],
        today=proposed_on,
    )
    assert (pending.subject, pending.proposal_id) == ("live_setting", "behind_live")
    assert pending.as_of_day == proposed_on
    assert pending.counted == 1
    assert pending.entries[0].cited is True


def test_a_pending_approval_does_not_double_count_the_reviews_that_fed_it() -> None:
    """The exact quirk this pins: on the approval day, before the looser setting takes effect
    tomorrow, the two reviews that already fed the approved proposal must not be shown as freshly
    counted toward a next proposal that was never made."""
    proposed_on = TODAY - timedelta(days=2)
    reviews = [
        _receipt_review("one", opened_day=proposed_on, minutes=1),
        _receipt_review("two", opened_day=proposed_on, minutes=2),
    ]
    proposals = [
        _proposal(
            "approved", minutes=5, day=proposed_on, cited=("one", "two"), triggers=("one", "two")
        )
    ]
    facts = [
        _approval(
            "approval", minutes=6, effective=proposed_on + timedelta(days=1), proposal_id="approved"
        )
    ]
    receipt = build_receipt(
        reviews=reviews, proposals=proposals, facts=facts, decisions=[], today=proposed_on
    )

    assert (receipt.subject, receipt.proposal_id) == ("live_setting", "approved")
    assert receipt.counted == 2
    assert {entry.review_id for entry in receipt.entries if entry.cited} == {"one", "two"}
    assert _standing(receipt) == {
        "one": ("counted_toward_loosening", None),
        "two": ("counted_toward_loosening", None),
    }


def test_a_decision_links_every_review_the_approved_proposal_counted() -> None:
    """Once live, every review in the approved proposal's `trigger_review_ids` links to the
    approval decision, not only the single review `ReceiptDecision.trigger_review_id` names."""
    proposed_on = TODAY - timedelta(days=5)
    reviews = [
        _receipt_review("one", opened_day=proposed_on, minutes=1),
        _receipt_review("two", opened_day=proposed_on, minutes=2),
    ]
    proposals = [
        _proposal(
            "approved", minutes=5, day=proposed_on, cited=("one", "two"), triggers=("one", "two")
        )
    ]
    facts = [
        _approval(
            "approval", minutes=6, effective=proposed_on + timedelta(days=1), proposal_id="approved"
        )
    ]
    decisions = [
        # The stored decision row only names the single review that triggered the write, the way
        # the repository writes it -- the receipt must still link both.
        ReceiptDecision(
            "approval",
            decided_at=T0 + timedelta(minutes=6),
            trigger_review_id="two",
            proposal_id="approved",
        )
    ]
    receipt = build_receipt(
        reviews=reviews, proposals=proposals, facts=facts, decisions=decisions, today=TODAY
    )

    by_id = {entry.review_id: entry for entry in receipt.entries}
    assert by_id["one"].led_to_decision_id == "approval"
    assert by_id["two"].led_to_decision_id == "approval"


def test_a_review_links_the_retry_s_approval_not_the_rejection_before_it() -> None:
    """Rejection -> retry -> approval in one round: the rejection feeds the same reviews into the
    retry, so both reviews reach the rejection first. What they led to is the approval that
    changed review timing, whichever review the stored decision rows name, in any input order."""
    proposed_on = TODAY - timedelta(days=5)
    reviews = [
        _receipt_review("one", opened_day=proposed_on, minutes=1),
        _receipt_review("two", opened_day=proposed_on, minutes=2),
    ]
    proposals = [
        _proposal(
            "first", minutes=5, day=proposed_on, cited=("one", "two"), triggers=("one", "two")
        ),
        _proposal(
            "retry", minutes=8, day=proposed_on, cited=("one", "two"), triggers=("one", "two")
        ),
    ]
    rejection = ThresholdDecisionFact(
        decision_id="rejection",
        kind=ReviewThresholdDecisionKind.REJECTED,
        previous=ReviewThreshold(40, 3),
        # A rejection records the value it turned down; it never applied.
        after=ReviewThreshold(40, 4),
        decided_on_day=proposed_on,
        effective_from_day=proposed_on,
        decided_at=T0 + timedelta(minutes=7),
        proposal_id="first",
    )
    facts = [
        rejection,
        _approval(
            "approval", minutes=9, effective=proposed_on + timedelta(days=1), proposal_id="retry"
        ),
    ]
    decisions = [
        # Both rows name only the last review, the way the repository writes them.
        ReceiptDecision(
            "rejection",
            decided_at=T0 + timedelta(minutes=7),
            trigger_review_id="two",
            proposal_id="first",
        ),
        ReceiptDecision(
            "approval",
            decided_at=T0 + timedelta(minutes=9),
            trigger_review_id="two",
            proposal_id="retry",
        ),
    ]
    for ordered in (decisions, list(reversed(decisions))):
        receipt = build_receipt(
            reviews=reviews, proposals=proposals, facts=facts, decisions=ordered, today=TODAY
        )
        by_id = {entry.review_id: entry for entry in receipt.entries}
        assert by_id["one"].led_to_decision_id == "approval"
        assert by_id["two"].led_to_decision_id == "approval"
        assert by_id["one"].led_to_proposal_id == "first"

    # With no change in the round, the earliest decision still names what the review led to.
    rejected_only = build_receipt(
        reviews=reviews,
        proposals=proposals,
        facts=[rejection],
        decisions=decisions[:1],
        today=TODAY,
    )
    assert {entry.led_to_decision_id for entry in rejected_only.entries} == {"rejection"}


@pytest.mark.parametrize(
    ("direction", "proposer"),
    [
        ("sooner", ReviewThresholdProposer.FIXED_RULE),
        ("sooner", ReviewThresholdProposer.AGENT),
        ("looser", ReviewThresholdProposer.COORDINATOR),
        ("sooner", ReviewThresholdProposer.COORDINATOR),
        ("no_change", ReviewThresholdProposer.STARTING_SETTING),
    ],
)
def test_a_proposal_no_review_counted_toward_is_never_the_subject(
    direction: ReceiptDirection, proposer: ReviewThresholdProposer
) -> None:
    """The receipt reports reviews "counted toward loosening", so only a looser proposal the
    calibrator made may be its subject. An asking-sooner proposal or a coordinator's own set, open
    or live, leaves the receipt describing the next proposal as of today."""
    proposed_on = TODAY - timedelta(days=4)
    reviews = [
        _receipt_review("one", opened_day=proposed_on, minutes=1),
        _receipt_review("two", opened_day=TODAY - timedelta(days=1), minutes=30),
    ]
    subject = _proposal(
        "subject",
        minutes=5,
        day=proposed_on,
        cited=("one",),
        direction=direction,
        proposer=proposer,
    )

    open_receipt = build_receipt(
        reviews=reviews,
        proposals=[replace(subject, is_open=True)],
        facts=[],
        decisions=[],
        today=TODAY,
    )
    live_receipt = build_receipt(
        reviews=reviews,
        proposals=[subject],
        facts=[
            _approval(
                "approval",
                minutes=6,
                effective=proposed_on + timedelta(days=1),
                proposal_id="subject",
            )
        ],
        decisions=[],
        today=TODAY,
    )
    for receipt in (open_receipt, live_receipt):
        assert (receipt.subject, receipt.proposal_id) == ("next_proposal", None)
        assert receipt.as_of_day == TODAY
        # Nothing is excluded as "after" a proposal that no review counted toward.
        assert _standing(receipt)["two"] == ("counted_toward_loosening", None)
        assert not any(entry.cited for entry in receipt.entries)
    # The live setting still starts the count, whoever set it.
    assert live_receipt.counted_from_day == proposed_on + timedelta(days=1)
    assert _standing(live_receipt)["one"] == ("excluded", "before_current_setting")


def test_an_open_sooner_proposal_leaves_a_live_loosening_as_the_subject() -> None:
    proposed_on = TODAY - timedelta(days=6)
    reviews = [_receipt_review("one", opened_day=proposed_on, minutes=1)]
    proposals = [
        _proposal("behind_live", minutes=5, day=proposed_on, cited=("one",)),
        _proposal("sooner", minutes=50, is_open=True, direction="sooner"),
    ]
    facts = [
        _approval(
            "approval",
            minutes=6,
            effective=proposed_on + timedelta(days=1),
            proposal_id="behind_live",
        )
    ]
    receipt = build_receipt(
        reviews=reviews, proposals=proposals, facts=facts, decisions=[], today=TODAY
    )
    assert (receipt.subject, receipt.proposal_id) == ("live_setting", "behind_live")
    assert receipt.counted == 1


def test_receipt_rule_is_plain_coordinator_wording_with_only_the_rule_s_numbers() -> None:
    assert coordinator_text_violations(RECEIPT_RULE) == []
    assert set(re.findall(r"\d+", RECEIPT_RULE)) == {
        str(FIXED_RULE_FALSE_ALARMS),
        str(FIXED_RULE_WINDOW_DAYS),
    }
    for summary in LESSON_SUMMARIES.values():
        assert re.search(r"\d", summary) is None, summary


# ── Guided `mdm-wong` sequence: the receipt agrees with the calibrator ─────────────────────────


def _active_run(session: Any, person_id: str) -> ScenarioRunRow:
    run = session.scalar(
        select(ScenarioRunRow).where(
            ScenarioRunRow.person_id == person_id, ScenarioRunRow.active.is_(True)
        )
    )
    assert run is not None
    return run


def _calibrator_counted(repository: SqlAlchemyRepository, person_id: str) -> frozenset[str]:
    """The reviews the calibrator would count for a `not_a_concern` trigger today.

    Runs the repository's own `_threshold_episode_context` and then `fixed_rule_output`, with a
    trigger that is no stored review, so `cited` names exactly the counted in-window alarms.
    """
    with repository.sessions() as session:
        run = _active_run(session, person_id)
        reviews = list(
            session.scalars(select(CaseReviewRow).where(CaseReviewRow.run_id == run.run_id))
        )
        if not reviews:
            return frozenset()
        trigger = reviews[0]
        episode = repository._threshold_episode_context(
            session,
            run.run_id,
            trigger_case_id=trigger.case_id,
            trigger_review_ids=(trigger.review_id,),
            reported_by=None,
            round_id=None,
            round_index=0,
        )
        assert episode is not None
        output = fixed_rule_output(
            live=episode.live,
            trigger_reason=OverrideReason.NOT_A_CONCERN,
            trigger=FalseAlarmRef(review_id="not_a_stored_review", opened_day=episode.current_day),
            not_a_concern_alarms=episode.not_a_concern_alarms,
            today=episode.current_day,
            blocked_values=frozenset(),
        )
        return frozenset(output.cited) & {review.review_id for review in reviews}


def _counted(receipt: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        entry["review_id"] for entry in receipt["entries"] if entry["status"] == COUNTED.value
    )


def _entry(receipt: dict[str, Any], review_id: str) -> dict[str, Any]:
    return next(entry for entry in receipt["entries"] if entry["review_id"] == review_id)


def test_the_guided_sequence_receipt_counts_what_the_calibrator_counts(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    reviews: list[str] = []

    # Chapter 1: one not-a-concern review; the fixed rule waits for a second.
    _play(client, CHAPTER_1)
    reviews.append(
        _review_api(
            client, status="resolved", human_action="override", override_reason="not_a_concern"
        )
    )
    state = _state(client)
    receipt = state["receipt"]
    assert receipt["subject"] == "next_proposal"
    assert receipt["as_of_day"] == state["current_day"]
    assert (receipt["needed"], receipt["counted"]) == (FIXED_RULE_FALSE_ALARMS, 1)
    assert _counted(receipt) == _calibrator_counted(repository, PERSON) == {reviews[0]}
    no_change = state["proposals"][0]
    assert _entry(receipt, reviews[0])["led_to_proposal_id"] == no_change["proposal_id"]
    assert _entry(receipt, reviews[0])["cited"] is False

    # Chapter 2: the second review opens the fixed rule's proposal.
    _play(client, CHAPTER_2)
    reviews.append(
        _review_api(
            client, status="resolved", human_action="override", override_reason="not_a_concern"
        )
    )
    calibrator = _calibrator_counted(repository, PERSON)
    state = _state(client)
    receipt = state["receipt"]
    proposal = state["open_proposal"]
    assert (receipt["subject"], receipt["proposal_id"]) == (
        "open_proposal",
        proposal["proposal_id"],
    )
    assert receipt["as_of_day"] == proposal["proposed_on_day"]
    assert receipt["counted_from_day"] is None
    assert receipt["counted"] == 2
    assert _counted(receipt) == calibrator == set(reviews)
    # What the stored proposal cited is what the receipt says counted.
    assert (
        {e["review_id"] for e in receipt["entries"] if e["cited"]}
        == (set(proposal["cited_evidence_ids"]) & set(reviews))
        == set(reviews)
    )
    assert [entry["review_id"] for entry in receipt["entries"]] == list(reversed(reviews))
    assert _entry(receipt, reviews[1])["led_to_proposal_id"] == proposal["proposal_id"]

    approved = client.post(
        f"{THRESHOLD}/proposals/{proposal['proposal_id']}/approve",
        json={"cause_confirmed": True, "shown_on_day": state["current_day"]},
    )
    assert approved.status_code == 200, approved.text
    _play(client, CHAPTER_3[:1])

    # The approved setting is live: the receipt is the approved proposal's, unchanged.
    state = _state(client)
    live_receipt = state["receipt"]
    assert (live_receipt["subject"], live_receipt["proposal_id"]) == (
        "live_setting",
        proposal["proposal_id"],
    )
    assert live_receipt["as_of_day"] == proposal["proposed_on_day"]
    assert _counted(live_receipt) == set(reviews)
    approval_id = state["live_decision_id"]

    # Chapter 3 is quiet; chapter 4's "should have reached me sooner" reverts from tomorrow.
    _play(client, CHAPTER_3[1:])
    _play(client, CHAPTER_4)
    late = _review_api(client, status="acknowledged", human_action="agree", reached_too_late=True)
    state = _state(client)
    receipt = state["receipt"]
    assert state["live_decision_id"] == approval_id
    assert receipt["subject"] == "live_setting"
    revert = state["decisions"][0]
    assert revert["kind"] == "reverted"
    assert _entry(receipt, late)["exclusion"] == "after_proposal"
    assert _entry(receipt, late)["led_to_decision_id"] == revert["decision_id"]
    assert _entry(receipt, late)["lesson"]["reason"] == "reached_too_late"

    # Tomorrow the starting setting is back: earlier reviews no longer count toward loosening.
    advanced = client.post(
        "/v1/simulation/advance", json={"event": "activity_declines", "person_id": PERSON}
    )
    assert advanced.status_code == 200, advanced.text
    state = _state(client)
    receipt = state["receipt"]
    assert receipt["subject"] == "next_proposal"
    assert receipt["as_of_day"] == state["current_day"]
    assert receipt["counted_from_day"] == revert["effective_from_day"]
    assert receipt["counted"] == 0
    assert _counted(receipt) == _calibrator_counted(repository, PERSON) == frozenset()
    assert _entry(receipt, late)["status"] == "asked_sooner"
    for review_id in reviews:
        assert _entry(receipt, review_id)["exclusion"] == "before_current_setting"

    text = json.dumps({"receipt": receipt, "context_gaps": state["context_gaps"]})
    assert DEMO_NOTE not in text
    assert "coordinator@" not in text and '"reviewer"' not in text
    for entry in receipt["entries"]:
        assert coordinator_text_violations(entry["lesson"]["summary"]) == []


def test_a_rejected_proposal_s_reviews_link_to_the_retry_s_approval(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Through the routes: reject the fixed rule's proposal, approve its retry. Every review the
    receipt links to a decision links to the approval, never the rejection before it."""
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    reviews: list[str] = []
    _play(client, CHAPTER_1)
    reviews.append(
        _review_api(
            client, status="resolved", human_action="override", override_reason="not_a_concern"
        )
    )
    _play(client, CHAPTER_2)
    reviews.append(
        _review_api(
            client, status="resolved", human_action="override", override_reason="not_a_concern"
        )
    )
    first = _state(client)["open_proposal"]
    rejected = client.post(
        f"{THRESHOLD}/proposals/{first['proposal_id']}/reject",
        json={"reason": "prefer_other_change"},
    )
    assert rejected.status_code == 200, rejected.text
    rejection_id = rejected.json()["decision"]["decision_id"]
    state = rejected.json()["state"]
    retry = state["open_proposal"]
    assert retry is not None and retry["proposal_id"] != first["proposal_id"]
    assert set(retry["trigger_review_ids"]) == set(first["trigger_review_ids"])
    approved = client.post(
        f"{THRESHOLD}/proposals/{retry['proposal_id']}/approve",
        json={"cause_confirmed": True, "shown_on_day": state["current_day"]},
    )
    assert approved.status_code == 200, approved.text
    approval_id = approved.json()["decision"]["decision_id"]

    receipt = _state(client)["receipt"]
    linked = {
        entry["review_id"]: entry["led_to_decision_id"]
        for entry in receipt["entries"]
        if entry["led_to_decision_id"] is not None
    }
    assert set(first["trigger_review_ids"]) <= set(linked)
    assert set(linked.values()) == {approval_id}
    assert rejection_id not in linked.values()


def test_an_open_asking_sooner_proposal_is_not_reported_as_counted_toward_loosening(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """A late review with nothing loosened opens a one-step-sooner proposal. The receipt must not
    present it as "N of 2 counted toward loosening"."""
    for index in range(3):
        response = client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "event_id": f"sooner-receipt-{index}"},
        )
        assert response.status_code == 200, response.text
    [case] = client.get("/v1/coordinator/queue").json()
    reviewed = client.post(
        f"/v1/cases/{case['case_id']}/review",
        json={
            "status": "acknowledged",
            "reviewer_note": "Should have come sooner.",
            "human_action": "agree",
            "reached_too_late": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text

    state = repository.review_threshold_state(DEMO_PERSON_ID, viewer_sub="coordinator")
    proposal = state.open_proposal
    assert proposal is not None and proposal.proposed is not None
    assert ReviewThreshold.from_value(proposal.proposed).stricter_than(
        ReviewThreshold.from_value(proposal.previous)
    )
    receipt = state.receipt
    assert (receipt.subject, receipt.proposal_id) == ("next_proposal", None)
    assert receipt.as_of_day == state.current_day
    assert receipt.counted == 0
    [entry] = receipt.entries
    assert entry.status == ReviewReceiptStatus.ASKED_SOONER
    assert entry.led_to_proposal_id == proposal.proposal_id


def _review_api(client: TestClient, **body: Any) -> str:
    return str(_review(client, _open_case(client), **body)["review_evidence_id"])


# ── Generated histories: the receipt agrees with the calibrator ────────────────────────────────

_GRID_REVIEWS: list[tuple[str, str, str | None, str | None, bool | None]] = [
    ("resolved", "coordinator", "override", "not_a_concern", False),
    ("resolved", "coordinator", "override", "not_a_concern", False),
    ("resolved", "coordinator", "override", "not_a_concern", None),
    ("acknowledged", "coordinator", "override", "not_a_concern", False),
    ("resolved", "coordinator", "override", "known_context", False),
    ("resolved", "coordinator", "override", "data_doubt", False),
    ("resolved", "coordinator", "override", "recent_contact", False),
    ("resolved", "coordinator", "override", "other", False),
    ("resolved", "coordinator", "agree", None, False),
    ("acknowledged", "coordinator", "agree", None, True),
    ("resolved", "coordinator", "override", "known_context", True),
    ("resolved", "coordinator", None, None, None),
    ("resolved", "system", None, None, None),
]
_GRID_OPENED: list[int | None] = [None, 0, 1, 2, 5, 9, 15, 28, 29, 30, 31, 45]
GRID_SEEDS = range(16)


@pytest.fixture
def grid_repository() -> Iterator[SqlAlchemyRepository]:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_OFFLINE))
    instance.create_schema_for_tests()
    instance.reset()
    yield instance
    instance.close()


def _seed_history(repository: SqlAlchemyRepository, rng: random.Random, seed: int) -> None:
    template_id = repository.list_cases()[0].case_id
    columns = [attr.key for attr in inspect(ReviewCaseRow).column_attrs]
    base = _utcnow() - timedelta(hours=2)
    with repository.sessions.begin() as session:
        run = _active_run(session, DEMO_PERSON_ID)
        today = run.current_day
        template = session.get(ReviewCaseRow, template_id)
        assert template is not None
        if rng.random() < 0.6:
            effective = today - timedelta(days=rng.choice([0, 1, 3, 10, 29, 40]))
            approval_id = f"grid_{seed}_approval"
            session.add(_decision_row(run, approval_id, "approved", effective, base, after=(40, 4)))
            if rng.random() < 0.4:
                reverted = effective + timedelta(days=rng.randint(0, (today - effective).days))
                row = _decision_row(
                    run, f"grid_{seed}_revert", "reverted", reverted, base, after=(40, 3)
                )
                row.previous_severity_pct, row.previous_persistence_days = 40, 4
                row.ends_approval_id = approval_id
                row.decided_at = base + timedelta(seconds=1)
                session.add(row)
        for index in range(rng.randint(2, 7)):
            status, reviewer, action, reason, late = rng.choice(_GRID_REVIEWS)
            offset = rng.choice(_GRID_OPENED)
            case = ReviewCaseRow(**{key: getattr(template, key) for key in columns})
            case.case_id = f"grid_{seed}_case_{index}"
            case.opened_day = None if offset is None else today - timedelta(days=offset)
            case.status = status
            session.add(case)
            session.flush()
            session.add(
                CaseReviewRow(
                    review_id=f"grid_{seed}_review_{index}",
                    case_id=case.case_id,
                    run_id=run.run_id,
                    status=status,
                    reviewer=reviewer,
                    note="grid note",
                    recorded_at=base + timedelta(minutes=index + 1),
                    human_action=action,
                    override_reason=reason,
                    reached_too_late=late,
                )
            )


def _decision_row(
    run: ScenarioRunRow,
    decision_id: str,
    kind: str,
    effective: date,
    at: datetime,
    *,
    after: tuple[int, int],
) -> ReviewThresholdDecisionRow:
    return ReviewThresholdDecisionRow(
        decision_id=decision_id,
        run_id=run.run_id,
        person_id=run.person_id,
        kind=kind,
        previous_severity_pct=40,
        previous_persistence_days=3,
        severity_pct=after[0],
        persistence_days=after[1],
        decided_by="coordinator" if kind == "approved" else "system",
        replay_json=None,
        decided_on_day=effective - timedelta(days=1),
        effective_from_day=effective,
        decided_at=at,
    )


@pytest.mark.parametrize("seed", GRID_SEEDS)
def test_generated_histories_count_what_the_calibrator_counts(
    grid_repository: SqlAlchemyRepository, seed: int
) -> None:
    repository = grid_repository
    for index in range(3):
        repository.advance("activity_declines", event_id=f"receipt-grid-{seed}-{index}")
    rng = random.Random(seed)
    _seed_history(repository, rng, seed)

    state = repository.review_threshold_state(DEMO_PERSON_ID, viewer_sub="coordinator")
    receipt = state.receipt
    assert receipt.subject == "next_proposal"
    assert receipt.as_of_day == state.current_day
    counted = frozenset(e.review_id for e in receipt.entries if e.status == COUNTED)
    assert counted == _calibrator_counted(repository, DEMO_PERSON_ID)
    assert receipt.counted == len(counted)

    with repository.sessions() as session:
        rows = {
            row.review_id: row
            for row in session.scalars(
                select(CaseReviewRow).where(CaseReviewRow.review_id.like(f"grid_{seed}_%"))
            )
        }
    assert {entry.review_id for entry in receipt.entries} == set(rows)
    for entry in receipt.entries:
        assert entry.lesson == repository._review_lesson(rows[entry.review_id])
        assert (entry.status == ReviewReceiptStatus.EXCLUDED) == (entry.exclusion is not None)
        assert "grid note" not in entry.model_dump_json()


def test_the_generated_grid_reaches_every_standing_but_after_proposal() -> None:
    """Keeps the seeds above honest: together they exercise every placement the receipt makes
    without a proposal (`after_proposal` needs one, and is pinned in the pure tests)."""
    seen: set[tuple[ReviewReceiptStatus, ReviewReceiptExclusion | None]] = set()
    for seed in GRID_SEEDS:
        repository = SqlAlchemyRepository(
            "sqlite+pysqlite:///:memory:", settings=Settings(**_OFFLINE)
        )
        repository.create_schema_for_tests()
        repository.reset()
        try:
            for index in range(3):
                repository.advance("activity_declines", event_id=f"receipt-cover-{seed}-{index}")
            _seed_history(repository, random.Random(seed), seed)
            receipt = repository.review_threshold_state(
                DEMO_PERSON_ID, viewer_sub="coordinator"
            ).receipt
            seen |= {(entry.status, entry.exclusion) for entry in receipt.entries}
        finally:
            repository.close()
    expected = {
        (COUNTED, None),
        (ReviewReceiptStatus.ASKED_SOONER, None),
        *(
            (ReviewReceiptStatus.EXCLUDED, exclusion)
            for exclusion in ReviewReceiptExclusion
            if exclusion != ReviewReceiptExclusion.AFTER_PROPOSAL
        ),
    }
    assert expected <= seen


# ── Lessons over the API ──────────────────────────────────────────────────────────────────────

LESSON_NOTE = "She walked 4321 steps with her daughter on Sunday."


def _open_demo_case(client: TestClient) -> str:
    for index in range(6):
        response = client.post(
            "/v1/simulation/advance",
            json={
                "event": "activity_declines",
                "person_id": DEMO_PERSON_ID,
                "event_id": f"lesson-{index}",
            },
        )
        assert response.status_code == 200, response.text
        cases = [
            case
            for case in client.get("/v1/coordinator/queue").json()
            if case["person_id"] == DEMO_PERSON_ID
        ]
        if cases:
            return str(cases[0]["case_id"])
    raise AssertionError("no review case opened after six declining days")


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({"status": "resolved", "human_action": "agree"}, "agreed"),
        ({"status": "acknowledged", "human_action": "hold"}, "on_hold"),
        ({"status": "resolved"}, "no_structured_choice"),
        (
            {"status": "resolved", "human_action": "override", "override_reason": "data_doubt"},
            "data_doubt",
        ),
        (
            {"status": "resolved", "human_action": "override", "override_reason": "recent_contact"},
            "recent_contact",
        ),
        (
            {"status": "resolved", "human_action": "override", "override_reason": "other"},
            "other_reason",
        ),
        (
            {"status": "resolved", "human_action": "override", "override_reason": "not_a_concern"},
            "not_a_concern",
        ),
        (
            {
                "status": "acknowledged",
                "human_action": "override",
                "override_reason": "not_a_concern",
            },
            "not_resolved",
        ),
        (
            {
                "status": "resolved",
                "human_action": "override",
                "override_reason": "known_context",
                "context_gap_category": "resting_or_recovering",
            },
            "known_context",
        ),
        (
            {"status": "acknowledged", "human_action": "agree", "reached_too_late": True},
            "reached_too_late",
        ),
        (
            {
                "status": "resolved",
                "human_action": "override",
                "override_reason": "known_context",
                "reached_too_late": True,
            },
            "reached_too_late",
        ),
    ],
)
def test_every_review_response_carries_the_lesson_of_its_stored_row(
    client: TestClient,
    repository: SqlAlchemyRepository,
    body: dict[str, Any],
    reason: str,
) -> None:
    case_id = _open_demo_case(client)
    response = client.post(
        f"/v1/cases/{case_id}/review", json={"reviewer_note": LESSON_NOTE, **body}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    with repository.sessions() as session:
        row = session.get(CaseReviewRow, result["review_evidence_id"])
        assert row is not None
        expected = repository._review_lesson(row)
    assert result["lesson"] == expected.model_dump(mode="json")
    assert result["lesson"]["reason"] == reason
    assert LESSON_NOTE not in result["lesson"]["summary"]
    assert "4321" not in json.dumps(result["lesson"])
    assert coordinator_text_violations(result["lesson"]["summary"]) == []

    state = client.get(f"/v1/coordinator/people/{DEMO_PERSON_ID}/review-threshold").json()
    receipt_text = json.dumps({"receipt": state["receipt"], "context_gaps": state["context_gaps"]})
    assert LESSON_NOTE not in receipt_text
    assert "4321" not in receipt_text
    assert _entry(state["receipt"], result["review_evidence_id"])["lesson"] == result["lesson"]


def test_nothing_new_reaches_the_senior_screens(client: TestClient) -> None:
    case_id = _open_demo_case(client)
    response = client.post(
        f"/v1/cases/{case_id}/review",
        json={
            "reviewer_note": LESSON_NOTE,
            "status": "resolved",
            "human_action": "override",
            "override_reason": "known_context",
            "context_gap_category": "resting_or_recovering",
        },
    )
    assert response.status_code == 200, response.text
    summary = response.json()["lesson"]["summary"]
    for path in (
        f"/v1/people/{DEMO_PERSON_ID}/state",
        f"/v1/evaluator/people/{DEMO_PERSON_ID}/senior-home",
    ):
        screen = client.get(path)
        assert screen.status_code == 200, (path, screen.text)
        text = screen.text
        for marker in ("lesson", "receipt", "context_gap", "resting_or_recovering", RECEIPT_RULE):
            assert marker not in text, (path, marker)
        assert summary not in text


# ── Guards: the agent sees no lesson, and a category changes nothing ───────────────────────────


def test_the_calibration_agent_payloads_carry_no_category_or_lesson(
    repository: SqlAlchemyRepository,
) -> None:
    for index in range(6):
        repository.advance("activity_declines", event_id=f"agent-guard-{index}")
        if repository.list_cases(person_id=DEMO_PERSON_ID):
            break
    case_id = repository.list_cases(person_id=DEMO_PERSON_ID)[0].case_id
    result = repository.review_case(
        case_id,
        CaseStatus.RESOLVED,
        LESSON_NOTE,
        human_action=HumanAction.OVERRIDE,
        override_reason=OverrideReason.KNOWN_CONTEXT,
        context_gap_category=ContextGapCategory.RESTING_OR_RECOVERING,
    )
    with repository.sessions() as session:
        run = _active_run(session, DEMO_PERSON_ID)
        context = repository._threshold_context_for(
            session,
            run,
            today=run.current_day,
            live=ReviewThreshold(40, 3),
            trigger_review_id=result.review_evidence_id,
            coordinator_reason=OverrideReason.KNOWN_CONTEXT,
            blocked_values=frozenset(),
        )
    text = json.dumps({"payloads": dict(context.payloads), "summaries": dict(context.summaries)})
    assert "review:" in text  # the review itself is visible, by alias
    for marker in ("context_gap", "resting_or_recovering", "lesson", "records_context_gap"):
        assert marker not in text, marker
    for lesson_summary in LESSON_SUMMARIES.values():
        assert lesson_summary not in text


def _run_story(category: ContextGapCategory | None) -> dict[str, Any]:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_OFFLINE))
    repository.create_schema_for_tests()
    repository.reset()
    try:
        steps = 0

        def open_case() -> str:
            nonlocal steps
            for _ in range(8):
                steps += 1
                repository.advance("activity_declines", event_id=f"story-{steps}")
                cases = [
                    case
                    for case in repository.list_cases(person_id=DEMO_PERSON_ID)
                    if case.status != CaseStatus.RESOLVED
                ]
                if cases:
                    return cases[0].case_id
            raise AssertionError("no case opened")

        def recover() -> None:
            nonlocal steps
            steps += 1
            repository.advance("recovery", event_id=f"story-{steps}")

        repository.review_case(
            open_case(),
            CaseStatus.RESOLVED,
            "note",
            human_action=HumanAction.OVERRIDE,
            override_reason=OverrideReason.KNOWN_CONTEXT,
            context_gap_category=category,
        )
        recover()
        for _ in range(2):
            repository.review_case(
                open_case(),
                CaseStatus.RESOLVED,
                "note",
                human_action=HumanAction.OVERRIDE,
                override_reason=OverrideReason.NOT_A_CONCERN,
            )
            recover()
        for _ in range(3):
            steps += 1
            repository.advance("activity_declines", event_id=f"story-{steps}")

        state = repository.review_threshold_state(DEMO_PERSON_ID, viewer_sub="coordinator")
        with repository.sessions() as session:
            run = _active_run(session, DEMO_PERSON_ID)
            decisions = [
                (row.observed_at.date(), row.decision, list(row.reasons_json))
                for row in session.scalars(
                    select(DecisionEvidenceRow)
                    .where(DecisionEvidenceRow.run_id == run.run_id)
                    .order_by(DecisionEvidenceRow.observed_at)
                )
            ]
            proposals = [
                (
                    row.output_kind,
                    row.proposer,
                    row.previous_severity_pct,
                    row.previous_persistence_days,
                    row.proposed_severity_pct,
                    row.proposed_persistence_days,
                    row.cause,
                    row.reasoning,
                    row.proposed_on_day,
                    len(row.cited_evidence_ids),
                )
                for row in session.scalars(
                    select(ReviewThresholdProposalRow)
                    .where(ReviewThresholdProposalRow.run_id == run.run_id)
                    .order_by(ReviewThresholdProposalRow.proposed_at)
                )
            ]
            threshold_decisions = [
                (row.kind, row.severity_pct, row.persistence_days, row.effective_from_day)
                for row in session.scalars(
                    select(ReviewThresholdDecisionRow).where(
                        ReviewThresholdDecisionRow.run_id == run.run_id
                    )
                )
            ]
        return {
            "decisions": decisions,
            "proposals": proposals,
            "threshold_decisions": threshold_decisions,
            "live": state.live.model_dump(),
            "open": state.open_proposal is not None,
            "standing": [
                (entry.status, entry.exclusion, entry.lesson.reason)
                for entry in state.receipt.entries
            ],
            "counted": state.receipt.counted,
            "gaps": state.context_gaps.by_category,
        }
    finally:
        repository.close()


def test_a_context_gap_category_changes_no_decision_proposal_or_threshold_row() -> None:
    without = _run_story(None)
    assert without["proposals"], "the story should reach the calibrator"
    assert any(kind == "no_change" for kind, *_ in without["proposals"])
    for category in (ContextGapCategory.AWAY, ContextGapCategory.OTHER_KNOWN):
        story = _run_story(category)
        assert story["gaps"] != without["gaps"]
        for key in (
            "decisions",
            "proposals",
            "threshold_decisions",
            "live",
            "open",
            "standing",
            "counted",
        ):
            assert story[key] == without[key], key
