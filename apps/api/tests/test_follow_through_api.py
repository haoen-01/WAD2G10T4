"""The follow-through loop over HTTP: detail, follow-through, follow-up, suppression.

Outreach used to end at the sentence. A person tapped "Yes, tell me more", saw nothing more, and
the tap was filed as a success. These tests cover the three beats that closes: showing what was
offered, asking later whether it actually happened, and looking at the days afterwards.

Everything here runs through the FastAPI contract rather than the repository directly, because
the ordering rules (`accepted` first, then exactly one follow-through) are only a real guarantee
if they are enforced at the edge a browser can reach.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.db_models import InterventionOutcomeRow, InterventionRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.learning import PreferenceLearner
from silverloop.sql_repository import SqlAlchemyRepository

DECLINE = "activity_declines"
SENIOR_SHELL_VOCABULARY = re.compile(r"\b(?:stable|watch|review|\d+%)\b", re.IGNORECASE)


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


def _follow_through(client: TestClient, intervention_id: str, value: str, note: str | None = None):
    body: dict[str, object] = {"follow_through": value}
    if note is not None:
        body["note"] = note
    return client.post(f"/v1/interventions/{intervention_id}/follow-through", json=body)


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
    client: TestClient,
) -> None:
    """`_preference_learners` rebuilds both posteriors from scratch on every read. If the reason
    were applied only on the write path the score would move back on the next request."""
    intervention = _offer(client)
    recorded = _outcome(
        client, intervention["intervention_id"], "declined", reason="bad_day"
    ).json()

    metrics = client.get("/v1/metrics").json()
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


# ── Detail: the button leads somewhere ────────────────────────────────────────────────────────


def test_detail_returns_real_content_for_the_candidate_that_was_offered(
    client: TestClient,
) -> None:
    intervention = _offer(client)

    response = client.get(f"/v1/interventions/{intervention['intervention_id']}/detail")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["kind"] == "movement_routine"
    assert len(detail["steps"]) >= 3
    assert detail["stop_note"].strip()
    assert detail["boundary_note"].strip()


def test_detail_matches_the_interventions_own_candidate_key(client: TestClient) -> None:
    """Not "some movement content" -- the content for the option this person was actually sent."""
    from silverloop.outreach_content import detail_for

    intervention = _offer(client)
    candidate_key = intervention["evidence"]["candidate_key"]

    detail = client.get(f"/v1/interventions/{intervention['intervention_id']}/detail").json()

    assert detail["title"] == detail_for(candidate_key).title


def test_detail_carries_no_coordinator_vocabulary_over_the_wire(client: TestClient) -> None:
    """The senior shell's guard, asserted on the payload rather than only on the rendered page."""
    intervention = _offer(client)

    detail = client.get(f"/v1/interventions/{intervention['intervention_id']}/detail").json()

    strings = [detail["title"], detail["intro"], detail["stop_note"], detail["boundary_note"]]
    strings.extend(step["text"] for step in detail["steps"])
    for value in strings:
        match = SENIOR_SHELL_VOCABULARY.search(value)
        assert match is None, f"{match.group(0)!r} in {value!r}"


def test_detail_is_readable_before_any_outcome_is_recorded(client: TestClient) -> None:
    """Reading is not answering. Looking at what was suggested must not close the intervention."""
    intervention = _offer(client)

    detail = client.get(f"/v1/interventions/{intervention['intervention_id']}/detail")
    assert detail.status_code == 200, detail.text

    current = client.get("/v1/interventions").json()[0]
    assert current["status"] == "proposed"
    assert current["outcome"] is None


def test_detail_for_an_unknown_intervention_is_404(client: TestClient) -> None:
    assert client.get("/v1/interventions/intervention_nope/detail").status_code == 404


# ── Follow-through: ordering and single-shot ──────────────────────────────────────────────────


def test_follow_through_before_acceptance_is_rejected(client: TestClient) -> None:
    """There is nothing to follow through on until the person has asked to see it."""
    intervention = _offer(client)

    response = _follow_through(client, intervention["intervention_id"], "completed")

    assert response.status_code == 422, response.text
    assert response.json()["detail"]


@pytest.mark.parametrize("outcome", ["declined", "deferred", "no_response"])
def test_follow_through_after_a_non_acceptance_is_rejected(
    client: TestClient, outcome: str
) -> None:
    """Someone who said no, "maybe later", or nothing at all was never shown the routine.

    Accepting a `completed` here would let the loop manufacture success out of a refusal.
    """
    intervention = _offer(client)
    assert _outcome(client, intervention["intervention_id"], outcome).status_code == 200

    response = _follow_through(client, intervention["intervention_id"], "completed")

    assert response.status_code == 422, response.text


def test_follow_through_is_recorded_once_and_only_once(client: TestClient) -> None:
    """One intervention, one unit of evidence -- enforced at the edge, not only in the learner."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    assert _outcome(client, intervention_id, "accepted").status_code == 200

    first = _follow_through(client, intervention_id, "completed")
    assert first.status_code == 200, first.text

    repeat = _follow_through(client, intervention_id, "unable")
    assert repeat.status_code == 422, repeat.text

    # The repeat changed nothing: the original answer stands.
    assert client.get("/v1/interventions").json()[0]["follow_through"] == "completed"


def test_a_reported_completion_moves_the_posterior_further_than_the_tap_did(
    client: TestClient,
) -> None:
    """The integrity fix, observed end to end rather than only in the unit test."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]

    accepted = _outcome(client, intervention_id, "accepted").json()
    tap_movement = accepted["preference_after"] - accepted["preference_before"]

    completed = _follow_through(client, intervention_id, "completed")
    assert completed.status_code == 200, completed.text
    payload = completed.json()
    reported_movement = payload["preference_after"] - payload["preference_before"]

    assert payload["follow_through"] == "completed"
    assert payload["candidate_key"] == accepted["candidate_key"]
    assert payload["follow_through_evidence_id"]
    assert reported_movement > 0
    assert reported_movement > tap_movement


def test_an_unable_report_ranks_the_option_down_without_judging_the_person(
    client: TestClient,
) -> None:
    """`unable` is a statement about the option, so it must lower the option's score -- and the
    audit trail must not describe it as anything else."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    _outcome(client, intervention_id, "accepted")

    payload = _follow_through(client, intervention_id, "unable").json()

    assert payload["preference_after"] < payload["preference_before"]
    assert payload["audit_event"]["detail"]["follow_through"] == "unable"


# ── "How was it?" is a question about having been there ───────────────────────────────────────


def _enjoyment(client: TestClient, intervention_id: str, verdict: str, liked: list[str]):
    return client.post(
        f"/v1/interventions/{intervention_id}/enjoyment",
        json={"enjoyment": verdict, "liked": liked},
    )


@pytest.mark.parametrize("follow_through", ["not_this_time", "unable"])
def test_enjoyment_on_an_outing_that_never_happened_is_refused(
    client: TestClient, follow_through: str
) -> None:
    """Audit D §2, reproduced live: "not this time" followed by "I enjoyed it, I liked the
    people" wrote `social`, `distance` and `timing` into the dimensional learner -- and the
    senior was then told Care+ had learned they prefer activities with other people, about
    something they did not attend. The gate is server-side because the web gate alone is a
    suggestion, not a rule."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    assert _outcome(client, intervention_id, "accepted").status_code == 200
    assert _follow_through(client, intervention_id, follow_through).status_code == 200

    refused = _enjoyment(client, intervention_id, "enjoyed", ["people", "location", "timing"])
    assert refused.status_code == 422, refused.text
    assert "went" in refused.json()["detail"]
    for word in ("stable", "watch", "review"):
        assert word not in refused.json()["detail"]

    # Nothing was inferred, and nothing was recorded.
    dimensions = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()
    assert dimensions["dimensions"] == []
    assert client.get("/v1/interventions").json()[0]["enjoyment"] is None


@pytest.mark.parametrize("follow_through", ["completed", "partial"])
def test_enjoyment_after_an_attending_report_is_still_recorded(
    client: TestClient, follow_through: str
) -> None:
    """The gate must not close the loop it exists to protect: `partial` is attendance too."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    _outcome(client, intervention_id, "accepted")
    assert _follow_through(client, intervention_id, follow_through).status_code == 200

    recorded = _enjoyment(client, intervention_id, "enjoyed", ["people"])
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["enjoyment"] == "enjoyed"


def test_enjoyment_before_any_follow_through_is_still_refused(client: TestClient) -> None:
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    _outcome(client, intervention_id, "accepted")

    refused = _enjoyment(client, intervention_id, "enjoyed", [])
    assert refused.status_code == 422, refused.text


def test_follow_through_appends_audit_evidence(client: TestClient) -> None:
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    _outcome(client, intervention_id, "accepted")
    before = len(client.get("/v1/simulation/events").json())

    payload = _follow_through(client, intervention_id, "partial", note="Did some of it.").json()

    after = client.get("/v1/simulation/events").json()
    assert len(after) == before + 1
    assert payload["audit_event"]["detail"]["intervention_id"] == intervention_id
    assert any(event["event_id"] == payload["audit_event"]["event_id"] for event in after)


def test_follow_through_for_an_unknown_intervention_is_404(client: TestClient) -> None:
    response = _follow_through(client, "intervention_nope", "completed")
    assert response.status_code == 404


def test_an_invalid_follow_through_value_is_rejected_by_the_contract(client: TestClient) -> None:
    intervention = _offer(client)
    _outcome(client, intervention["intervention_id"], "accepted")

    response = _follow_through(client, intervention["intervention_id"], "smashed_it")

    assert response.status_code == 422


# ── Follow-up: descriptive, never causal, never silent ────────────────────────────────────────


def test_follow_up_is_always_200_and_always_carries_the_caveat(client: TestClient) -> None:
    """ "Too early to say" is a normal answer, not an error, and it still carries the warning."""
    intervention = _offer(client)

    response = client.get(f"/v1/interventions/{intervention['intervention_id']}/follow-up")

    assert response.status_code == 200, response.text
    observation = response.json()
    assert observation["intervention_id"] == intervention["intervention_id"]
    assert observation["caveat"].strip()
    if not observation["available"]:
        assert observation["reason_unavailable"]


def test_follow_up_is_unavailable_immediately_after_outreach(client: TestClient) -> None:
    """No days have happened yet. Reporting a number here would be the overclaim the whole
    module is built to avoid."""
    intervention = _offer(client)

    observation = client.get(
        f"/v1/interventions/{intervention['intervention_id']}/follow-up"
    ).json()

    assert observation["available"] is False
    assert observation["change_percent"] == 0
    assert observation["returned_toward_usual"] is False


def test_follow_up_for_an_unknown_intervention_is_404(client: TestClient) -> None:
    assert client.get("/v1/interventions/intervention_nope/follow-up").status_code == 404


def test_outreach_history_joins_what_was_offered_to_what_happened(client: TestClient) -> None:
    """One shape serving the senior's history, the coordinator column and the ops panel, so the
    three cannot drift into telling different stories about the same event."""
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    _outcome(client, intervention_id, "accepted")
    _follow_through(client, intervention_id, "completed")

    response = client.get("/v1/interventions/history")

    assert response.status_code == 200, response.text
    summaries = response.json()
    entry = next(item for item in summaries if item["intervention_id"] == intervention_id)
    assert entry["person_id"] == DEMO_PERSON_ID
    assert entry["outcome"] == "accepted"
    assert entry["follow_through"] == "completed"
    assert entry["candidate_key"] == intervention["evidence"]["candidate_key"]
    assert entry["follow_up"] is None or entry["follow_up"]["caveat"].strip()


def test_a_reset_does_not_carry_the_previous_runs_outreach_into_history(
    client: TestClient,
    repository: SqlAlchemyRepository,
) -> None:
    """ADR 0004, the same rule `_outreach_responses` (the world model) already follows: a reset
    starts the story over, so the previous run's outreach is not this run's history. That has to
    hold for every surface `list_outreach_summaries` backs -- the senior's own history and the
    coordinator's outreach-history column, not only the world model's narrative facts.

    Nothing is deleted, and the person-level learner (`_preference_learners`, read here through
    `GET /v1/metrics`) is unaffected by the reset -- a posterior is about the person, not one demo
    run, exactly as it is for `_suppress_after_repeated_declines`'s cross-run decline count
    (`test_a_candidate_is_suppressed_after_three_declines`, above).
    """
    intervention = _offer(client)
    intervention_id = intervention["intervention_id"]
    outcome = _outcome(client, intervention_id, "declined", reason="not_for_me").json()
    candidate_key = outcome["candidate_key"]

    def _history_ids(path: str) -> set[str]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        return {item["intervention_id"] for item in response.json()}

    senior_path = "/v1/interventions/history"
    coordinator_path = f"/v1/coordinator/people/{DEMO_PERSON_ID}/outreach-history"

    assert intervention_id in _history_ids(senior_path)
    assert intervention_id in _history_ids(coordinator_path)

    preference_before_reset = client.get("/v1/metrics").json()["candidate_preference_scores"][
        candidate_key
    ]

    assert client.post("/v1/demo/reset").status_code == 200

    assert intervention_id not in _history_ids(senior_path)
    assert intervention_id not in _history_ids(coordinator_path)

    # Not deleted, only out of this run's story -- the rows are exactly where they were.
    with repository.sessions() as session:
        row = session.get(InterventionRow, intervention_id)
        assert row is not None
        outcomes = session.scalars(
            select(InterventionOutcomeRow).where(
                InterventionOutcomeRow.intervention_id == intervention_id
            )
        ).all()
    assert [entry.outcome for entry in outcomes] == ["declined"]

    # The person-level posterior that reads every run's outcomes is untouched by the reset.
    preference_after_reset = client.get("/v1/metrics").json()["candidate_preference_scores"][
        candidate_key
    ]
    assert preference_after_reset == preference_before_reset


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


def test_a_candidate_is_suppressed_after_three_declines(client: TestClient) -> None:
    """Deterministic and separate from the learner: three declines removes the option from the
    permitted set rather than merely ranking it lower."""
    _decline_cycle(client, 9)

    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences").json()
    suppressed = [item for item in preferences if item["suppressed"]]

    assert suppressed, f"expected at least one suppressed candidate, got {preferences}"
    for item in suppressed:
        assert item["declines"] >= 3
        assert item["suppressed_reason"]


def test_a_suppressed_candidate_is_no_longer_offered(client: TestClient) -> None:
    """Muting has to change what is *sent*, not merely what is stored.

    Suppressed here directly rather than through three declines, because the decline path also
    advances the ladder and this test is about the permitted set alone.
    """
    muted_key = "gentle_nudge:indoor_walk"
    assert (
        client.post(
            f"/v1/people/{DEMO_PERSON_ID}/preferences/{muted_key}",
            json={"suppressed": True, "reason": "Not for me."},
        ).status_code
        == 200
    )

    intervention = _offer(client)

    assert intervention["evidence"]["candidate_key"] != muted_key
    # The muted option is not merely ranked last -- it never entered the ranking. Suppression
    # narrows the permitted set; it is not a thumb on the learner's scale.
    ranking = intervention["evidence"]["candidate_ranking"]
    assert ranking, "the ranking evidence must still be recorded"
    assert muted_key not in {item["candidate_key"] for item in ranking}


def test_when_every_candidate_is_suppressed_the_result_is_an_audited_no_action(
    client: TestClient,
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
        muted = client.post(
            f"/v1/people/{DEMO_PERSON_ID}/preferences/{candidate_key}",
            json={"suppressed": True, "reason": "Not for me."},
        )
        assert muted.status_code == 200, muted.text

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
    events = client.get("/v1/simulation/events").json()
    assert any(event["event_id"] == payload["audit_event"]["event_id"] for event in events)


def test_a_senior_can_suppress_and_then_unsuppress_a_candidate(client: TestClient) -> None:
    """`suppressed` is reversible by the person, which is the reason it is theirs to write."""
    intervention = _offer(client)
    candidate_key = intervention["evidence"]["candidate_key"]

    muted = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/preferences/{candidate_key}",
        json={"suppressed": True, "reason": "Not for me."},
    )
    assert muted.status_code == 200, muted.text
    assert muted.json()["preference"]["suppressed"] is True
    assert muted.json()["audit_event"]["event_id"]

    restored = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/preferences/{candidate_key}",
        json={"suppressed": False, "reason": "Changed my mind."},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["preference"]["suppressed"] is False


def test_suppression_narrows_the_permitted_set_and_never_raises_a_decision_rung(
    client: TestClient,
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
        client.post(
            f"/v1/people/{DEMO_PERSON_ID}/preferences/{candidate_key}",
            json={"suppressed": True, "reason": "Not for me."},
        )
    _outcome(client, intervention["intervention_id"], "declined")
    client.post("/v1/demo/reset")

    payload = _advance(client)

    assert payload["state"]["last_decision"] in {"no_action", "suppress"}
    assert payload["created_case"] is None
    assert payload["created_intervention"] is None


# ── Day disputes: the person's account is kept beside the sensor's, never instead of it ────────


def test_a_day_dispute_is_recorded_without_rewriting_the_metric(client: TestClient) -> None:
    """Overwriting sensor data with self-report would destroy provenance; ignoring the person
    would be worse. The observation stays; a competing account is attached."""
    metrics = client.get(f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3").json()
    day = metrics[-1]["day"]
    steps_before = metrics[-1]["steps"]

    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/day-dispute",
        json={"day": day, "accurate": False, "note": "I was out all afternoon without my watch."},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["day"] == day
    assert payload["accurate"] is False
    assert payload["dispute_evidence_id"]
    assert payload["audit_event"]["event_id"]

    after = client.get(f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3").json()
    assert after[-1]["steps"] == steps_before


def test_a_dispute_for_a_day_with_no_record_is_404(client: TestClient) -> None:
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/day-dispute",
        json={"day": "2019-01-01", "accurate": False},
    )
    assert response.status_code == 404


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


def test_bad_day_declines_never_mute_a_candidate(client: TestClient) -> None:
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
    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences").json()
    assert not [item for item in preferences if item["suppressed"]]
