"""The outreach outcome loop over HTTP: answers, reasons, suppression.

Outreach used to end at the sentence. The outcome route is where the person's answer -- and the
reason they give for it -- enters the record, and these tests pin what that answer may and may not
change.

Everything here runs through the FastAPI contract where a browser can reach it, because the
ordering rules (one answer, then at most one reason attached to it) are only a real guarantee if
they are enforced at that edge. The detail, follow-through, follow-up, history, enjoyment,
day-dispute and mute routes this file also covered went in step 7; a mute or a dispute that
`advance` still reads is stored as a row (`tests/row_fixtures.py`).
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.learning import PreferenceLearner
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import audit_events, dispute_day, mute_candidate

DECLINE = "activity_declines"


def _advance(client: TestClient, event: str = DECLINE) -> dict:
    response = client.post("/v1/simulation/advance", json={"event": event})
    assert response.status_code == 200, response.text
    return response.json()


def _offer(client: TestClient) -> dict:
    """One advance that produces an actual piece of outreach."""
    payload = _advance(client)
    intervention = payload["created_intervention"]
    assert intervention is not None, "expected this advance to create an intervention"
    return intervention


def _outcome(client: TestClient, intervention_id: str, outcome: str, **extra: object):
    return client.post(
        f"/v1/interventions/{intervention_id}/outcome", json={"outcome": outcome, **extra}
    )


# ── `deferred` is a real answer ───────────────────────────────────────────────────────────────


def test_deferred_is_an_accepted_outcome(client: TestClient) -> None:
    """ "Maybe later" used to be rejected outright or filed as silence.

    The route's allow-list had four members and `deferred` was not one of them, so the senior
    UI's "Maybe later" button was recording `no_response` -- scoring an active reply from someone
    who read the message as if they had ignored it.
    """
    intervention = _offer(client)

    response = _outcome(client, intervention["intervention_id"], "deferred")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["outcome"] == "deferred"
    assert payload["intervention"]["outcome"] == "deferred"
    assert payload["outcome_evidence_id"].startswith("outcome_")


def test_deferred_is_audited_but_moves_no_preference(client: TestClient) -> None:
    """It is a first-class audited answer that happens to carry no ranking information."""
    intervention = _offer(client)

    payload = _outcome(client, intervention["intervention_id"], "deferred").json()

    assert payload["preference_after"] == payload["preference_before"]
    assert payload["audit_event"]["detail"]["outcome"] == "deferred"


def test_a_bad_day_decline_moves_no_preference_but_a_not_for_me_decline_does(
    client: TestClient,
) -> None:
    """The reason has always been stored on the outcome row and read by the suppression guard;
    until now it never reached the posterior that orders outreach, so "just a bad day" ranked an
    option down exactly as hard as "it is not for me". Asserted over HTTP because the wiring that
    was missing (`_preference_learners` selecting the column) sits between the two.
    """
    bad_day = _outcome(
        client, _offer(client)["intervention_id"], "declined", reason="bad_day"
    ).json()
    assert bad_day["preference_after"] == bad_day["preference_before"]

    refused = _outcome(
        client, _offer(client)["intervention_id"], "declined", reason="not_for_me"
    ).json()
    assert refused["preference_after"] < refused["preference_before"]


def test_an_already_active_decline_never_ranks_the_option_down(client: TestClient) -> None:
    """`already_active` corrects the tracker, not the suggestion."""
    payload = _outcome(
        client, _offer(client)["intervention_id"], "declined", reason="already_active"
    ).json()

    assert payload["preference_after"] == payload["preference_before"]


def test_a_recorded_reason_survives_a_rebuild_of_the_learner_from_the_outcome_rows(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """`_preference_learners` rebuilds both posteriors from scratch on every read. If the reason
    were applied only on the write path the score would move back on the next request."""
    intervention = _offer(client)
    recorded = _outcome(
        client, intervention["intervention_id"], "declined", reason="bad_day"
    ).json()

    metrics = repository.metrics().model_dump(mode="json")
    key = recorded["candidate_key"]

    assert metrics["candidate_preference_scores"][key] == recorded["preference_before"]


def test_activity_recovered_is_a_live_outcome_the_senior_route_accepts(
    client: TestClient,
) -> None:
    """Kept honest deliberately: `activity_recovered` has been described as a phantom outcome
    that no caller emits, which would have made its `_OUTCOME_WEIGHTS` entry dead code. It is
    not -- `record_outcome`'s allow-list carries it, so a client can post one today and it does
    reach the learner. This pins that, so the entry is justified by a live path rather than by
    prose.
    """
    response = _outcome(client, _offer(client)["intervention_id"], "activity_recovered")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["outcome"] == "activity_recovered"
    assert payload["preference_after"] > payload["preference_before"]


def test_coordinator_only_outcomes_are_still_rejected_on_the_senior_route(
    client: TestClient,
) -> None:
    """Widening the allow-list for `deferred` must not have widened it for everything."""
    intervention = _offer(client)

    response = _outcome(client, intervention["intervention_id"], "coordinator_resolved")

    assert response.status_code == 422
    assert "case review" in response.json()["detail"].lower()


# ── Suppression: the person narrows the permitted set, and it holds ───────────────────────────


def _decline_cycle(client: TestClient, rounds: int) -> list[str]:
    """Offer, decline, reset -- so every round starts on day one and stays at `gentle_nudge`.

    Returns the candidate key offered each round, or stops early once nothing is offered at all.
    """
    offered: list[str] = []
    for _ in range(rounds):
        payload = _advance(client)
        intervention = payload["created_intervention"]
        if intervention is None:
            break
        offered.append(intervention["evidence"]["candidate_key"])
        assert _outcome(client, intervention["intervention_id"], "declined").status_code == 200
        assert client.post("/v1/demo/reset").status_code == 200
    return offered


def _preferences(repository: SqlAlchemyRepository) -> list[dict]:
    """The person's own suggestion mutes (`GET /v1/people/{id}/preferences` until step 7)."""
    return [
        item.model_dump(mode="json")
        for item in repository.list_candidate_preferences(person_id=DEMO_PERSON_ID)
    ]


def _mute(repository: SqlAlchemyRepository, candidate_key: str) -> None:
    mute_candidate(repository, candidate_key, person_id=DEMO_PERSON_ID, reason="Not for me.")


def test_a_candidate_is_suppressed_after_three_declines(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Deterministic and separate from the learner: three declines removes the option from the
    permitted set rather than merely ranking it lower."""
    _decline_cycle(client, 9)

    preferences = _preferences(repository)
    suppressed = [item for item in preferences if item["suppressed"]]

    assert suppressed, f"expected at least one suppressed candidate, got {preferences}"
    for item in suppressed:
        assert item["declines"] >= 3
        assert item["suppressed_reason"]


def test_a_suppressed_candidate_is_no_longer_offered(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Muting has to change what is *sent*, not merely what is stored.

    Suppressed here directly rather than through three declines, because the decline path also
    advances the ladder and this test is about the permitted set alone.
    """
    muted_key = "gentle_nudge:indoor_walk"
    _mute(repository, muted_key)

    intervention = _offer(client)

    assert intervention["evidence"]["candidate_key"] != muted_key
    # The muted option is not merely ranked last -- it never entered the ranking. Suppression
    # narrows the permitted set; it is not a thumb on the learner's scale.
    ranking = intervention["evidence"]["candidate_ranking"]
    assert ranking, "the ranking evidence must still be recorded"
    assert muted_key not in {item["candidate_key"] for item in ranking}


def test_when_every_candidate_is_suppressed_the_result_is_an_audited_no_action(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """The edge case that decides whether suppression is a feature or an outage.

    With every movement option muted there is nothing the policy is permitted to send. That must
    be `NO_ACTION` with a reason and an audit event -- a first-class result -- and never a
    crash, an empty 500, or a silent skip that leaves nothing in the record at all.

    Set up by muting both options directly rather than by declining until each is muted: the decline
    route escalates the ladder as a side effect, so it cannot isolate "the ladder chose to send
    something and had nothing left to send".
    """
    for candidate_key in [
        "gentle_nudge:indoor_walk",
        "gentle_nudge:chair_mobility",
        "gentle_nudge:companion_walk",
    ]:
        _mute(repository, candidate_key)

    payload = _advance(client)

    assert payload["created_intervention"] is None
    assert payload["state"]["last_decision"] == "no_action"
    assert payload["state"]["rationale"], "a no-action decision must explain itself"
    assert any("muted" in reason for reason in payload["state"]["rationale"]), (
        "the reason has to say it was the person's own choice, not a system failure"
    )
    assert payload["audit_event"]["event_id"]
    assert payload["loop_trace"], "the trace is still produced for a no-action decision"

    # And it is genuinely in the audit trail, not merely in the response body.
    events = audit_events(repository, person_id=DEMO_PERSON_ID)
    assert any(event.event_id == payload["audit_event"]["event_id"] for event in events)


def test_suppression_narrows_the_permitted_set_and_never_raises_a_decision_rung(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """The invariant underneath the whole feature.

    Muting options is safety-preserving because it can only ever remove candidates. It must not
    push the ladder upward -- a person switching off suggestions must not be the thing that
    escalates them to a human.
    """
    intervention = _offer(client)
    for candidate_key in [
        "gentle_nudge:indoor_walk",
        "gentle_nudge:chair_mobility",
        "gentle_nudge:companion_walk",
    ]:
        _mute(repository, candidate_key)
    _outcome(client, intervention["intervention_id"], "declined")
    client.post("/v1/demo/reset")

    payload = _advance(client)

    assert payload["state"]["last_decision"] in {"no_action", "suppress"}
    assert payload["created_case"] is None
    assert payload["created_intervention"] is None


# ── Day disputes: the person's account is kept beside the sensor's, never instead of it ────────


def test_a_day_dispute_reaches_the_data_quality_assessment_without_rewriting_the_metric(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Overwriting sensor data with self-report would destroy provenance; ignoring the person
    would be worse. The observation stays; a competing account is attached, and the quality
    assessment reports that the two disagree."""
    metrics = client.get(f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3").json()
    day = metrics[-1]["day"]
    steps_before = metrics[-1]["steps"]

    dispute_day(
        repository,
        date.fromisoformat(day),
        accurate=False,
        person_id=DEMO_PERSON_ID,
        note="I was out all afternoon without my watch.",
    )

    after = client.get(f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3").json()
    assert after[-1]["steps"] == steps_before
    quality = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["signal"]["quality"]
    assert quality["self_reported_conflict"] is True
    assert quality["self_reported_conflict_note"] == "I was out all afternoon without my watch."


# ── Attaching a reason to an answer already given ─────────────────────────────────────────────
#
# The senior screen records "Not today" first and only then offers the optional reasons, because a
# refusal must save whether or not the person goes on to say why. That makes the reason arrive as
# a second POST to the same route -- straight into the duplicate-outcome guard. One narrow
# amendment is allowed through it, and these tests pin exactly how narrow.


def test_a_reason_can_be_attached_to_a_decline_already_recorded(client: TestClient) -> None:
    intervention = _offer(client)
    first = _outcome(client, intervention["intervention_id"], "declined")
    assert first.status_code == 200, first.text

    amended = _outcome(client, intervention["intervention_id"], "declined", reason="already_active")
    assert amended.status_code == 200, amended.text
    assert amended.json()["audit_event"]["event_type"] == "intervention_outcome_reason_added"


def test_attaching_a_reason_does_not_move_the_posterior_a_second_time(
    client: TestClient,
) -> None:
    """The property the duplicate guard exists to hold: one answer, one unit of evidence.

    A reason is context about an answer, not a second answer, so it must not be allowed to
    re-apply the decline's weight and rank the candidate down twice for one refusal. What it may
    do, now that declines are reason-keyed, is change the SIZE of that one unit: the senior screen
    records "Not today" first and offers the optional reasons afterwards, so `bad_day` arriving a
    moment later is the person finishing the same answer, and the amendment corrects the weight
    the bare decline provisionally applied. The invariant is "one unit", not "the number never
    moves" -- so this asserts against a learner fed exactly one observation rather than against
    the pre-amendment value.
    """
    intervention = _offer(client)
    first = _outcome(client, intervention["intervention_id"], "declined").json()
    amended = _outcome(client, intervention["intervention_id"], "declined", reason="bad_day").json()

    one_observation = PreferenceLearner()
    one_observation.record(amended["candidate_key"], "declined", reason="bad_day")
    assert amended["preference_after"] == one_observation.expected_value(amended["candidate_key"])

    # Not the doubly-charged value a second unit of evidence would have produced...
    doubled = PreferenceLearner()
    doubled.record(amended["candidate_key"], "declined")
    doubled.record(amended["candidate_key"], "declined", reason="bad_day")
    assert amended["preference_after"] != doubled.expected_value(amended["candidate_key"])

    # ...and the correction itself is reported honestly rather than hidden behind two identical
    # numbers: the bare decline had ranked the candidate down, and `bad_day` takes that back.
    assert amended["preference_before"] == first["preference_after"]
    assert amended["preference_after"] > amended["preference_before"]


def test_the_amendment_does_not_reopen_the_duplicate_outcome_guard(client: TestClient) -> None:
    """Everything other than "same answer, new reason" is still the rejected duplicate."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    assert _outcome(client, intervention_id, "declined").status_code == 200

    # A bare repeat, with nothing new to add.
    assert _outcome(client, intervention_id, "declined").status_code == 422
    # A different answer, smuggled in behind a reason.
    assert _outcome(client, intervention_id, "accepted", reason="bad_day").status_code == 422

    # And once a reason is stored, it cannot be overwritten by a later one.
    assert _outcome(client, intervention_id, "declined", reason="already_active").status_code == 200
    assert _outcome(client, intervention_id, "declined", reason="not_for_me").status_code == 422


def test_declining_because_already_active_reaches_the_data_quality_assessment(
    client: TestClient,
) -> None:
    """The loop no wearable closes on its own: the person correcting the sensor.

    It must mark the day contested without being able to flip `safe_to_interpret` -- whether a
    reading is interpretable is decided by wear time, and a self-report is not wear time.
    """
    intervention = _offer(client)
    _outcome(client, intervention["intervention_id"], "declined")
    _outcome(client, intervention["intervention_id"], "declined", reason="already_active")

    quality = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["signal"]["quality"]
    assert quality["self_reported_conflict"] is True
    assert quality["self_reported_conflict_note"]
    assert quality["safe_to_interpret"] is True, (
        "a person's own account must not be able to decide whether a reading is interpretable"
    )


def test_bad_day_declines_never_mute_a_candidate(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """A "just not today" says nothing about the option, so three of them never count toward
    suppression -- the same boundary the dimensional learner keeps."""
    offered: list[str] = []
    for _ in range(6):
        payload = _advance(client)
        intervention = payload["created_intervention"]
        if intervention is None:
            break
        offered.append(intervention["evidence"]["candidate_key"])
        assert (
            _outcome(
                client, intervention["intervention_id"], "declined", reason="bad_day"
            ).status_code
            == 200
        )
        assert client.post("/v1/demo/reset").status_code == 200
    assert offered
    assert not [item for item in _preferences(repository) if item["suppressed"]]
