"""The candidate-baseline release, exercised through the real `advance()` / `_evaluate` path.

`test_baseline_confirmation.py` pins the pure decision in `baseline_confirmation.question_for`.
These tests pin the durable half: that a confirmation actually re-anchors the reference for every
evaluation from here on, and that a decline changes nothing but the cooldown. The senior's answer
is stored as a row (`tests/row_fixtures.py`): the route and repository method that wrote it went
in step 7, and what `_evaluate` does with the row is unchanged.
"""

from __future__ import annotations

from silverloop.baseline_confirmation import DECLINE_COOLDOWN_DAYS
from silverloop.models import AdvanceResponse, BaselineConfirmationDecision, Decision
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import decide_baseline_confirmation


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def _decline_until_pending(repository: SqlAlchemyRepository, *, limit: int = 60) -> AdvanceResponse:
    response: AdvanceResponse | None = None
    for index in range(limit):
        response = repository.advance("activity_declines", event_id=f"decline-{index}")
        if response.state.pending_baseline_confirmation is not None:
            return response
    raise AssertionError(
        f"pending_baseline_confirmation never appeared within {limit} declining days"
    )


def test_a_sustained_decline_eventually_asks_whether_it_is_the_new_normal() -> None:
    repository = _repo()
    try:
        response = _decline_until_pending(repository)
        question = response.state.pending_baseline_confirmation
        assert question is not None
        assert question.streak_days > 0
        # The clamp must actually still be binding when the question fires, or this would be
        # asking about nothing.
        assert response.state.baseline.effective_median_steps > response.state.baseline.median_steps
    finally:
        repository.close()


def test_confirming_re_anchors_the_reference_and_clears_the_clamp() -> None:
    repository = _repo()
    try:
        response = _decline_until_pending(repository)
        person_id = response.state.person_id
        rolling_median = response.state.baseline.median_steps
        previous_reference = response.state.baseline.reference_steps

        reference_steps = decide_baseline_confirmation(
            repository, BaselineConfirmationDecision.CONFIRM, person_id=person_id
        )
        assert reference_steps == rolling_median
        assert reference_steps != previous_reference

        after = repository.person_state(person_id=person_id)
        assert after.baseline.reference_steps == rolling_median
        assert after.baseline.effective_median_steps == after.baseline.median_steps
        assert after.pending_baseline_confirmation is None
        # The person is still living at the same (now-normal) level: no further escalation.
        assert after.last_decision in (Decision.NO_ACTION, Decision.GENTLE_NUDGE)
    finally:
        repository.close()


def test_declining_leaves_the_clamp_bound_and_starts_a_cooldown() -> None:
    repository = _repo()
    try:
        response = _decline_until_pending(repository)
        person_id = response.state.person_id
        clamped_effective = response.state.baseline.effective_median_steps
        reference_before = response.state.baseline.reference_steps

        reference_steps = decide_baseline_confirmation(
            repository, BaselineConfirmationDecision.DECLINE, person_id=person_id
        )
        assert reference_steps == reference_before

        after = repository.person_state(person_id=person_id)
        assert after.baseline.reference_steps == reference_before
        assert after.baseline.effective_median_steps == clamped_effective
        assert after.pending_baseline_confirmation is None

        # Still within the cooldown: continuing to decline must not ask again.
        for index in range(min(10, DECLINE_COOLDOWN_DAYS - 1)):
            follow_up = repository.advance("activity_declines", event_id=f"cooldown-{index}")
        assert follow_up.state.pending_baseline_confirmation is None
    finally:
        repository.close()


def test_the_cooldown_expires_and_the_question_returns() -> None:
    repository = _repo()
    try:
        response = _decline_until_pending(repository)
        person_id = response.state.person_id
        decide_baseline_confirmation(
            repository, BaselineConfirmationDecision.DECLINE, person_id=person_id
        )

        last = None
        for index in range(DECLINE_COOLDOWN_DAYS + 5):
            last = repository.advance("activity_declines", event_id=f"post-decline-{index}")
        assert last is not None
        assert last.state.pending_baseline_confirmation is not None
    finally:
        repository.close()


def test_confirmation_never_changes_what_policy_permits() -> None:
    """The safety invariant: re-anchoring changes what counts as this person's normal, never what
    the consent/safety ladder in `policy.py` allows. A confirmed reference must not, for example,
    make outreach reach someone whose consent is inactive.
    """
    repository = _repo()
    try:
        response = _decline_until_pending(repository)
        person_id = response.state.person_id
        decide_baseline_confirmation(
            repository, BaselineConfirmationDecision.CONFIRM, person_id=person_id
        )
        repository.set_consent(False, "Senior withdrew consent.", "senior", person_id=person_id)
        after = repository.person_state(person_id=person_id)
        assert after.last_decision == Decision.SUPPRESS
        assert after.permitted_actions == [Decision.SUPPRESS]
    finally:
        repository.close()
