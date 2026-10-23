"""The guided scenario "A false alarm teaches Care+", driven with the calibration agent on.

Shared by the recorder (`synthesise.record_threshold`) and the replay test
(`tests/test_review_threshold_recording.py`), so the recorded requests and the replayed ones come
from the identical sequence -- a sequence defined twice would key differently and miss.

It drives the real repository on in-memory SQLite: `mdm-wong`, the fixed demo note, the four
episodes of the Simulator's guided scenario (spec section 11). With the agent on, the story can
differ from the offline one (the agent may propose on the first false alarm); whatever proposal
appears at an interlude is approved, as the interlude tells the demo operator to do.

Imported explicitly, never by `silverloop.evaluation` itself: the evaluation packages must not
import the repository layer, and this module does, lazily.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

PERSON = "mdm-wong"
DEMO_NOTE = "Mdm Wong's activity swings a lot from week to week; this is her usual pattern."
COORDINATOR = "coordinator"

# (events, interlude): E1 and E2 end with a "not a concern" review (and any proposal approved);
# E3 is quiet; E4 ends with "this should have reached me sooner".
EPISODES: tuple[tuple[tuple[str, ...], str | None], ...] = (
    (("activity_declines",) * 3, "not_a_concern"),
    (("recovery",), None),
    (("activity_declines",) * 3, "not_a_concern"),
    (("recovery",), None),
    (("activity_declines",) * 3, None),
    (("recovery",), None),
    (("activity_declines",) * 4, "reached_too_late"),
)


def run_guided_threshold_sequence(
    *, settings: Any, client_factory: Callable[[], tuple[Any, str | None]] | None
) -> Any:
    """Play the sequence on a fresh in-memory repository and return its final threshold state.

    `client_factory` is passed to `SqlAlchemyRepository(threshold_client_factory=...)`: a recording
    client when recording, a replaying one (or `None`, for the configured provider) when replaying.
    """
    from silverloop.models import CaseStatus, HumanAction, OverrideReason
    from silverloop.sql_repository import SqlAlchemyRepository

    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=settings,
        threshold_client_factory=client_factory,
    )
    try:
        repository.create_schema_for_tests()
        repository.reset(person_id=PERSON)
        step = 0
        for events, interlude in EPISODES:
            for event in events:
                step += 1
                repository.advance(event, event_id=f"guided-threshold-{step}", person_id=PERSON)
            if interlude is None:
                continue
            open_cases = [
                case
                for case in repository.list_cases(person_id=PERSON)
                if case.status != CaseStatus.RESOLVED
            ]
            if not open_cases:
                continue
            if interlude == "reached_too_late":
                repository.review_case(
                    open_cases[0].case_id,
                    CaseStatus.ACKNOWLEDGED,
                    DEMO_NOTE,
                    COORDINATOR,
                    human_action=HumanAction.AGREE,
                    reached_too_late=True,
                )
                continue
            repository.review_case(
                open_cases[0].case_id,
                CaseStatus.RESOLVED,
                DEMO_NOTE,
                COORDINATOR,
                human_action=HumanAction.OVERRIDE,
                override_reason=OverrideReason.NOT_A_CONCERN,
            )
            state = repository.review_threshold_state(PERSON, viewer_sub=COORDINATOR)
            if state.open_proposal is not None:
                repository.approve_threshold_proposal(
                    PERSON,
                    state.open_proposal.proposal_id,
                    cause_confirmed=True,
                    shown_on_day=state.current_day,
                    note=None,
                    actor=COORDINATOR,
                )
        return repository.review_threshold_state(PERSON, viewer_sub=COORDINATOR)
    finally:
        repository.close()


__all__ = ["DEMO_NOTE", "EPISODES", "PERSON", "run_guided_threshold_sequence"]
