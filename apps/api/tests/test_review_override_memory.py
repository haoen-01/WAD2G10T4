"""What the human decided, and whether they agreed with Care+ (audit-H finding 3 / F16).

Review was built as an audit checkbox: a status and a note. The web sent one of two canned
sentences, so nothing on record said what the coordinator chose to *do*, whether it matched
`ReviewCase.recommendation`, or why it did not -- which makes "is this system's judgement any
good?" an unanswerable question, and makes a disagreement indistinguishable from an agreement.

The last test in this module is the important one. Override memory is audit and evaluation only:
a coordinator overruling the system is not a training signal about which activity a senior enjoys,
and letting it reach the ranker would mean one human's decision about one person quietly
reweighting a different person's suggestions.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import CaseStatus, HumanAction, OverrideReason
from silverloop.sql_repository import SqlAlchemyRepository

REVIEWER_NOTE_SENTINEL = "Sentinel-Q7vb-coordinator-words-stay-on-the-review-row"


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def _open_case(repository: SqlAlchemyRepository, tag: str) -> str:
    for index in range(3):
        repository.advance("activity_declines", event_id=f"{tag}-{index}")
    return repository.list_cases()[0].case_id


def test_a_review_records_what_the_agent_suggested_and_what_the_human_chose() -> None:
    repository = _repo()
    try:
        case_id = _open_case(repository, "override")
        recommendation = repository.get_case(case_id).recommendation

        response = repository.review_case(
            case_id,
            CaseStatus.RESOLVED,
            "Closed after speaking to her.",
            reviewer="coordinator-amy",
            human_action=HumanAction.OVERRIDE,
            override_reason=OverrideReason.KNOWN_CONTEXT,
        )

        action = response.case.action_history[-1]
        assert action.human_action == HumanAction.OVERRIDE
        assert action.override_reason == OverrideReason.KNOWN_CONTEXT
        # Frozen at review time, not a pointer to a field a later refresh could rewrite: what the
        # human was looking at when they decided is the thing worth keeping.
        assert action.agent_recommendation == recommendation
    finally:
        repository.close()


def test_an_agreeing_review_records_agreement_rather_than_an_absent_reason() -> None:
    repository = _repo()
    try:
        case_id = _open_case(repository, "agree")

        response = repository.review_case(
            case_id,
            CaseStatus.ACKNOWLEDGED,
            "Agreed; will check in with her tomorrow.",
            reviewer="coordinator-amy",
            human_action=HumanAction.AGREE,
        )

        action = response.case.action_history[-1]
        assert action.human_action == HumanAction.AGREE
        # No reason is required when nobody is overruling anything, and none is invented.
        assert action.override_reason is None
    finally:
        repository.close()


def test_a_review_that_predates_the_structured_choice_still_works_and_claims_nothing() -> None:
    """The old two-field request stays valid. `None` reads as "not recorded", which is honest;
    defaulting it to `agree` would put words in a coordinator's mouth."""
    repository = _repo()
    try:
        case_id = _open_case(repository, "legacy")

        response = repository.review_case(
            case_id, CaseStatus.ACKNOWLEDGED, "Acknowledged.", "coordinator"
        )

        action = response.case.action_history[-1]
        assert (action.human_action, action.override_reason) == (None, None)
    finally:
        repository.close()


def test_an_override_without_a_reason_is_rejected(client: TestClient) -> None:
    client.post("/v1/demo/reset")
    for index in range(3):
        client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "event_id": f"reject-{index}"},
        )
    case_id = client.get("/v1/coordinator/queue").json()[0]["case_id"]

    rejected = client.post(
        f"/v1/cases/{case_id}/review",
        json={
            "status": "resolved",
            "reviewer_note": "Overruled without saying why.",
            "human_action": "override",
        },
    )
    accepted = client.post(
        f"/v1/cases/{case_id}/review",
        json={
            "status": "resolved",
            "reviewer_note": "Overruled, and here is why.",
            "human_action": "override",
            "override_reason": "recent_contact",
        },
    )

    assert rejected.status_code == 422, rejected.text
    assert accepted.status_code == 200, accepted.text


def test_the_coordinators_own_words_never_reach_the_operator_audit_trail(
    client: TestClient,
) -> None:
    """The same rule the senior's free-text fields already follow (`test_audit_redaction.py`).
    `GET /v1/simulation/events` is readable by any `demo_operator`, for any person; a note a
    coordinator typed about a senior is exactly the kind of text that must not be in it."""
    client.post("/v1/demo/reset")
    for index in range(3):
        client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "event_id": f"redact-{index}"},
        )
    case_id = client.get("/v1/coordinator/queue").json()[0]["case_id"]

    response = client.post(
        f"/v1/cases/{case_id}/review",
        json={
            "status": "acknowledged",
            "reviewer_note": REVIEWER_NOTE_SENTINEL,
            "human_action": "hold",
            "override_reason": "data_doubt",
        },
    )
    assert response.status_code == 200, response.text

    events = client.get("/v1/simulation/events", params={"person_id": DEMO_PERSON_ID})
    assert REVIEWER_NOTE_SENTINEL not in events.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["note_present"] is True
    assert detail["human_action"] == "hold"
    assert detail["override_reason"] == "data_doubt"
    # The words themselves survive where they belong: on the case, for the care team that wrote
    # them.
    case = client.get(f"/v1/cases/{case_id}").json()
    assert case["action_history"][-1]["note"] == REVIEWER_NOTE_SENTINEL


def test_metrics_counts_overrides_beside_the_reviews_they_came_from() -> None:
    repository = _repo()
    try:
        case_id = _open_case(repository, "count")
        assert repository.metrics().coordinator_overrides == 0

        repository.review_case(
            case_id,
            CaseStatus.ACKNOWLEDGED,
            "Agreed.",
            "amy",
            human_action=HumanAction.AGREE,
        )
        repository.review_case(
            case_id,
            CaseStatus.RESOLVED,
            "Actually, she told us she is away.",
            "amy",
            human_action=HumanAction.OVERRIDE,
            override_reason=OverrideReason.KNOWN_CONTEXT,
        )

        metrics = repository.metrics()
        # A count with its denominator beside it, never a rate: "1 override" alone says nothing.
        assert metrics.coordinator_overrides == 1
        assert metrics.coordinator_reviews == 2
    finally:
        repository.close()


def test_an_override_moves_no_preference_and_no_learner_reads_the_review_table() -> None:
    repository = _repo()
    try:
        case_id = _open_case(repository, "learning")
        before = repository.metrics()

        repository.review_case(
            case_id,
            CaseStatus.RESOLVED,
            "Overruled: we spoke to her yesterday.",
            "amy",
            human_action=HumanAction.OVERRIDE,
            override_reason=OverrideReason.RECENT_CONTACT,
        )

        after = repository.metrics()
        assert after.preference_scores == before.preference_scores
        assert after.candidate_preference_scores == before.candidate_preference_scores
    finally:
        repository.close()

    # The behavioural check above can only prove that today's override moved nothing today. This
    # one pins the structural reason it cannot: no module on the learning or ranking path knows
    # the review table exists.
    source_root = Path(__file__).resolve().parents[1] / "src" / "silverloop"
    learning_modules = [
        source_root / "learning.py",
        source_root / "preferences.py",
        source_root / "activity_search.py",
        source_root / "policy.py",
        *sorted((source_root / "evaluation" / "ranking").glob("*.py")),
    ]
    for module in learning_modules:
        # Scan the code, not the prose: a comment explaining *why* the learner never sees a
        # review is not a read of the review table. Names, attributes, imports and string
        # literals that reach the interpreter are what would be.
        tree = ast.parse(module.read_text())
        reached: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                reached.add(node.id)
            elif isinstance(node, ast.Attribute):
                reached.add(node.attr)
            elif isinstance(node, ast.alias):
                reached.add(node.name.split(".")[-1])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                reached.add(node.value)
        forbidden = {"CaseReviewRow", "case_reviews"}
        assert not (reached & forbidden), f"{module.name} must not read the review table"
