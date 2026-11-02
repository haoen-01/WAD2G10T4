"""The audit trail is an operator surface, so a person's own free text must never land in it
verbatim -- only whether the field was present, or how long it was. The note or reason itself
still has to survive somewhere: on its own domain row, which is queried directly here.

Of the routes that let a senior type something in their own words, the consent reason is the one
left after step 7 (the follow-through, day-dispute, context-question, candidate-preference and
review-setting routes went with no screen). It is driven through the real HTTP contract with a
distinctive sentinel string, and the assertion checks the *whole* stored audit trail for the
person, not just the one event just written -- an older event that still carried raw text would
pass a narrower check.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.db_models import (
    AuditEventRow,
    ConsentEvidenceRow,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

SENTINEL = "Sentinel-Zx91-never-leave-the-domain-row"


def _events(repository: SqlAlchemyRepository) -> list[dict]:
    """Every stored audit event for the person, as the operator-readable trail served them
    (`GET /v1/simulation/events`, removed in step 7)."""
    with repository.sessions() as session:
        rows = session.scalars(
            select(AuditEventRow).where(AuditEventRow.person_id == DEMO_PERSON_ID)
        ).all()
        return [repository._to_audit(row).model_dump(mode="json") for row in rows]


def _assert_sentinel_absent_from_audit_trail(repository: SqlAlchemyRepository) -> None:
    """Not just the one event just written -- the entire trail for this person."""
    assert SENTINEL not in str(_events(repository))


def test_consent_reason_never_reaches_the_audit_trail(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/consent",
        json={"active": False, "reason": SENTINEL},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["reason_length"] == len(SENTINEL)
    assert "reason" not in detail

    _assert_sentinel_absent_from_audit_trail(repository)

    with repository.sessions() as session:
        row = session.scalar(
            select(ConsentEvidenceRow)
            .where(ConsentEvidenceRow.person_id == DEMO_PERSON_ID)
            .order_by(ConsentEvidenceRow.recorded_at.desc())
        )
    assert row is not None and row.reason == SENTINEL
