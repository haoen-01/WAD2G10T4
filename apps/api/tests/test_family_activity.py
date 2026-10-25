"""The family activity feed and check-ins: what is recorded, what is not, and who may read it."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text

from silverloop.config import Settings
from silverloop.db_models import AccountRow, AuditEventRow, FamilyActivityRow
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_family_calendar import _member_b, _senior_person, _weekly
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
    _onboard,
    client,  # noqa: F401 - pytest fixture
)

_SOURCE = Path(__file__).resolve().parents[1] / "src" / "silverloop"
OWNER = "family-a"


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    """Shadows the shared `repo` fixture: the same in-memory database, but with foreign keys
    enforced. SQLite ignores them by default, so a feed row pointing at a deleted member (the demo
    reset's delete order) would otherwise pass here and only fail on PostgreSQL."""
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")

    @event.listens_for(repository.engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    repository.create_schema_for_tests()
    with repository.engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    repository.reset()
    return repository


def _feed(client: TestClient, group_id: str, sub: str = OWNER, **params: object):  # noqa: F811
    return client.get(f"/v1/groups/{group_id}/activity", params=params, headers=_headers(sub))


def _entries(client: TestClient, group_id: str, sub: str = OWNER) -> list[dict]:  # noqa: F811
    response = _feed(client, group_id, sub, limit=50)
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def _kinds(client: TestClient, group_id: str, sub: str = OWNER) -> list[str]:  # noqa: F811
    """Oldest first, for reading a story in order."""
    return [e["kind"] for e in reversed(_entries(client, group_id, sub))]


def _appointment_body(**changes: object) -> dict:
    return {
        "title": "Eye check-up",
        "kind": "medical",
        "date": "2026-11-12",
        "start": "09:30",
        "end": "10:30",
        **changes,
    }


def _new_appointment(client: TestClient, group_id: str, **changes: object) -> str:  # noqa: F811
    response = client.post(
        f"/v1/groups/{group_id}/appointments",
        json=_appointment_body(**changes),
        headers=_headers(OWNER),
    )
    assert response.status_code == 201, response.text
    return response.json()["appointment_id"]


def _window(day: str = "2026-11-05", start: str = "09:00", end: str = "12:00") -> dict:
    return {"date": day, "start": start, "end": end, "status": "available"}


# ── What each action records ──────────────────────────────────────────────────


def test_creating_the_group_records_group_created(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    [entry] = _entries(client, group_id)
    assert entry["kind"] == "group_created"
    assert entry["actor_name"] == "Wei Ling"
    assert entry["is_me"] is True
    assert entry["origin"] == "live"
    assert entry["subject_name"] is None and entry["appointment_id"] is None


def test_approving_records_the_new_member_and_declining_records_no_name(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    _member_b(client, group_id, approve=False)
    # A pending request is not an event.
    assert _kinds(client, group_id) == ["group_created"]

    group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
    pending = next(m for m in group["members"] if m["status"] == "pending")
    approved = client.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/approve", headers=_headers(OWNER)
    )
    assert approved.status_code == 200
    latest = _entries(client, group_id)[0]
    assert latest["kind"] == "member_approved"
    assert latest["actor_name"] == "Wei Ling"
    assert latest["subject_name"] == "Jun"

    _onboard(client, "family-c", "family", "Kai")
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Nephew"},
        headers=_headers("family-c"),
    )
    group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
    waiting = next(m for m in group["members"] if m["status"] == "pending")
    declined = client.post(
        f"/v1/groups/{group_id}/members/{waiting['member_id']}/decline", headers=_headers(OWNER)
    )
    assert declined.status_code == 200
    latest = _entries(client, group_id)[0]
    assert latest["kind"] == "member_declined"
    assert latest["subject_name"] is None
    assert "Kai" not in str(_entries(client, group_id))
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        row = session.scalar(
            select(FamilyActivityRow).where(FamilyActivityRow.kind == "member_declined")
        )
        assert row is not None and row.subject_member_id is None


def test_appointment_add_change_remove_each_record_one_entry_with_a_snapshot(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    appointment_id = _new_appointment(client, group_id)
    added = _entries(client, group_id)[0]
    assert added["kind"] == "appointment_added"
    assert added["appointment_title"] == "Eye check-up"
    assert added["appointment_kind"] == "medical"
    assert added["on_date"] == "2026-11-12"
    assert added["appointment_id"] == appointment_id
    assert added["occurrence_id"] == f"{appointment_id}@2026-11-12"

    changed = client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json=_appointment_body(title="Eye check-up (moved)", date="2026-11-13"),
        headers=_headers(OWNER),
    )
    assert changed.status_code == 200
    entries = _entries(client, group_id)
    assert [e["kind"] for e in entries[:2]] == ["appointment_changed", "appointment_added"]
    assert entries[0]["appointment_title"] == "Eye check-up (moved)"
    assert entries[0]["on_date"] == "2026-11-13"
    assert entries[0]["occurrence_id"] == f"{appointment_id}@2026-11-13"
    # The earlier entry's day is gone now that the appointment moved, and so is its link.
    assert entries[1]["on_date"] == "2026-11-12" and entries[1]["occurrence_id"] is None
    assert entries[1]["appointment_title"] == "Eye check-up"

    deleted = client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=_headers(OWNER)
    )
    assert deleted.status_code == 204
    entries = _entries(client, group_id)
    assert entries[0]["kind"] == "appointment_removed"
    assert entries[0]["appointment_title"] == "Eye check-up (moved)"
    assert entries[0]["occurrence_id"] is None
    assert all(e["occurrence_id"] is None for e in entries)
    assert len(entries) == 4  # created, added, changed, removed


def test_saving_an_appointment_unchanged_records_nothing(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    appointment_id = _new_appointment(client, group_id, location="Polyclinic", notes="Bring NRIC")
    base = _kinds(client, group_id)
    path = f"/v1/groups/{group_id}/appointments/{appointment_id}"
    same = client.put(
        path,
        json=_appointment_body(location=" Polyclinic ", notes="Bring NRIC"),
        headers=_headers(OWNER),
    )
    assert same.status_code == 200
    assert _kinds(client, group_id) == base

    for change in ({"notes": "Bring NRIC and the booklet"}, {"end": "11:00"}):
        response = client.put(
            path,
            json=_appointment_body(**{"location": "Polyclinic", "notes": "Bring NRIC", **change}),
            headers=_headers(OWNER),
        )
        assert response.status_code == 200
        base = [*base, "appointment_changed"]
        assert _kinds(client, group_id) == base
        # Put it back, which is a change too.
        client.put(
            path,
            json=_appointment_body(location="Polyclinic", notes="Bring NRIC"),
            headers=_headers(OWNER),
        )
        base = [*base, "appointment_changed"]
        assert _kinds(client, group_id) == base


def test_entries_about_a_repeating_appointment_link_to_no_single_day(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    owner = _headers(OWNER)
    appointment_id = _new_appointment(client, group_id, title="Tai Chi", repeat="weekly")
    added = _entries(client, group_id)[0]
    assert added["kind"] == "appointment_added"
    assert added["appointment_title"] == "Tai Chi"
    assert added["on_date"] is None and added["occurrence_id"] is None
    assert added["appointment_id"] == appointment_id

    path = f"/v1/groups/{group_id}/appointments/{appointment_id}"
    client.put(
        path, json=_appointment_body(title="Tai Chi", repeat="weekly", end="11:00"), headers=owner
    )
    changed = _entries(client, group_id)[0]
    assert changed["kind"] == "appointment_changed"
    assert changed["on_date"] is None and changed["occurrence_id"] is None

    # Turning a repeat off makes it a one-off again, so the entry points at its day.
    client.put(path, json=_appointment_body(title="Tai Chi", repeat="none"), headers=owner)
    one_off = _entries(client, group_id)[0]
    assert one_off["on_date"] == "2026-11-12"
    assert one_off["occurrence_id"] == f"{appointment_id}@2026-11-12"

    client.put(path, json=_appointment_body(title="Tai Chi", repeat="weekly"), headers=owner)
    client.post(f"{path}/delete", headers=owner)
    removed = _entries(client, group_id)[0]
    assert removed["kind"] == "appointment_removed"
    assert removed["on_date"] is None and removed["appointment_title"] == "Tai Chi"


def test_helper_joined_and_stepped_back_record_once_and_noops_record_nothing(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    appointment_id = _weekly(client, group_id, date(2026, 11, 2))
    day = f"{appointment_id}@2026-11-09"
    owner = _headers(OWNER)
    helpers = f"/v1/groups/{group_id}/helpers"
    base = len(_entries(client, group_id))  # created + appointment_added

    # Stepping back when not helping is nothing.
    client.post(f"{helpers}/step-back", json={"occurrence_id": day}, headers=owner)
    assert len(_entries(client, group_id)) == base

    client.post(helpers, json={"occurrence_id": day}, headers=owner)
    joined = _entries(client, group_id)[0]
    assert joined["kind"] == "helper_joined"
    assert joined["appointment_title"] == "Physio"
    assert joined["on_date"] == "2026-11-09"
    assert joined["occurrence_id"] == day

    # Volunteering again, while already helping, is nothing.
    client.post(helpers, json={"occurrence_id": day}, headers=owner)
    assert len(_entries(client, group_id)) == base + 1

    client.post(f"{helpers}/step-back", json={"occurrence_id": day}, headers=owner)
    assert _entries(client, group_id)[0]["kind"] == "helper_stepped_back"
    assert len(_entries(client, group_id)) == base + 2


def test_an_answer_records_only_when_it_removed_a_helper(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    appointment_id = _weekly(client, group_id, date(2026, 11, 2))
    day = f"{appointment_id}@2026-11-09"
    owner = _headers(OWNER)
    answers = f"/v1/groups/{group_id}/answers"
    base = len(_entries(client, group_id))

    for status in ("available", "unavailable"):  # neither is helping, so neither is news
        response = client.post(
            answers, json={"occurrence_id": day, "status": status}, headers=owner
        )
        assert response.status_code == 204
    assert len(_entries(client, group_id)) == base

    client.post(f"/v1/groups/{group_id}/helpers", json={"occurrence_id": day}, headers=owner)
    client.post(answers, json={"occurrence_id": day, "status": "unavailable"}, headers=owner)
    assert _kinds(client, group_id)[-2:] == ["helper_joined", "helper_stepped_back"]
    assert len(_entries(client, group_id)) == base + 2


def test_availability_edits_for_one_day_within_fifteen_minutes_are_one_entry(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    _member_b(client, group_id)
    owner = _headers(OWNER)
    path = f"/v1/groups/{group_id}/availability"
    first = client.post(path, json=_window(), headers=owner)
    client.post(path, json=_window(start="14:00", end="16:00"), headers=owner)
    client.post(f"{path}/{first.json()['entry_id']}/delete", headers=owner)
    updates = [e for e in _entries(client, group_id) if e["kind"] == "availability_updated"]
    assert len(updates) == 1
    assert updates[0]["on_date"] == "2026-11-05"
    assert updates[0]["appointment_id"] is None

    # Another day is another entry, and so is another member.
    client.post(path, json=_window(day="2026-11-06"), headers=owner)
    client.post(path, json=_window(), headers=_headers("family-b"))
    updates = [e for e in _entries(client, group_id) if e["kind"] == "availability_updated"]
    assert sorted((e["actor_name"], e["on_date"]) for e in updates) == [
        ("Jun", "2026-11-05"),
        ("Wei Ling", "2026-11-05"),
        ("Wei Ling", "2026-11-06"),
    ]


def test_availability_is_recorded_again_after_the_window(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    path = f"/v1/groups/{group_id}/availability"
    client.post(path, json=_window(), headers=_headers(OWNER))
    # Age the entry past the dedupe window; the table stays append-only for the app itself.
    with client.app.state.repository.sessions.begin() as session:  # type: ignore[attr-defined]
        row = session.scalar(
            select(FamilyActivityRow).where(FamilyActivityRow.kind == "availability_updated")
        )
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(minutes=16)
    client.post(path, json=_window(), headers=_headers(OWNER))
    kinds = _kinds(client, group_id)
    assert kinds.count("availability_updated") == 2


# ── Refused actions write nothing ─────────────────────────────────────────────


def test_refused_actions_record_nothing(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    appointment_id = _new_appointment(client, group_id)
    other_senior = _onboard(client, "senior-2", "senior", "Mr Goh")
    assert other_senior["person_id"]
    _onboard(client, "family-z", "family", "Zed")
    pin = client.post("/v1/me/link-pin", headers=_headers("senior-2")).json()["pin"]
    other_group = client.post(
        "/v1/groups",
        json={"senior_pin": pin, "relationship": "Son"},
        headers=_headers("family-z"),
    ).json()["group_id"]
    before = _kinds(client, group_id)
    other_before = _kinds(client, other_group, "family-z")
    zed = _headers("family-z")
    owner = _headers(OWNER)

    # A foreign appointment, a day it does not have, bad input, and an outsider.
    refusals = [
        client.put(
            f"/v1/groups/{other_group}/appointments/{appointment_id}",
            json=_appointment_body(),
            headers=zed,
        ),
        client.post(f"/v1/groups/{other_group}/appointments/{appointment_id}/delete", headers=zed),
        client.post(
            f"/v1/groups/{group_id}/helpers",
            json={"occurrence_id": f"{appointment_id}@2026-11-30"},
            headers=owner,
        ),
        client.post(
            f"/v1/groups/{group_id}/answers",
            json={"occurrence_id": "nope", "status": "unavailable"},
            headers=owner,
        ),
        client.post(
            f"/v1/groups/{group_id}/availability",
            json={**_window(), "start": "12:00", "end": "09:00"},
            headers=owner,
        ),
        client.post(f"/v1/groups/{group_id}/availability/missing/delete", headers=owner),
        client.post(f"/v1/groups/{group_id}/appointments", json=_appointment_body(), headers=zed),
        client.post(f"/v1/groups/{group_id}/check-ins", json={"kind": "called"}, headers=zed),
        client.post(f"/v1/groups/{group_id}/members/missing/approve", headers=owner),
        client.post(f"/v1/groups/{group_id}/members/missing/decline", headers=owner),
    ]
    assert [r.status_code for r in refusals] == [404, 404, 404, 404, 422, 404, 404, 404, 404, 404]
    assert _kinds(client, group_id) == before
    assert _kinds(client, other_group, "family-z") == other_before


# ── Reading the feed ──────────────────────────────────────────────────────────


def test_only_active_members_read_the_feed(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    _member_b(client, group_id, approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("family-b", "outsider"):  # pending, and not a member
        assert _feed(client, group_id, sub).status_code == 404
        assert (
            client.post(
                f"/v1/groups/{group_id}/check-ins", json={"kind": "called"}, headers=_headers(sub)
            ).status_code
            == 404
        )
    assert _feed(client, "grp_unknown").status_code == 404
    # The senior's own sign-in is not a family one.
    assert _feed(client, group_id, "senior-1").status_code == 403
    assert (
        client.post(
            f"/v1/groups/{group_id}/check-ins",
            json={"kind": "called"},
            headers=_headers("senior-1"),
        ).status_code
        == 403
    )


def test_a_page_size_outside_one_to_fifty_is_refused(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    assert _feed(client, group_id, limit=0).status_code == 422
    assert _feed(client, group_id, limit=51).status_code == 422
    assert _feed(client, group_id, limit=50).status_code == 200
    assert _feed(client, group_id, before="x" * 65).status_code == 422


def test_pages_are_ordered_disjoint_and_end_with_no_cursor(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    for index in range(6):
        response = client.post(
            f"/v1/groups/{group_id}/check-ins",
            json={"kind": "messaged", "note": f"note {index}"},
            headers=_headers(OWNER),
        )
        assert response.status_code == 201
    everything = _entries(client, group_id)
    assert len(everything) == 7

    seen: list[str] = []
    before: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": 3}
        if before:
            params["before"] = before
        body = _feed(client, group_id, **params).json()
        seen += [e["activity_id"] for e in body["entries"]]
        pages += 1
        before = body["next_before"]
        if before is None:
            break
    assert pages == 3
    assert seen == [e["activity_id"] for e in everything]
    assert len(set(seen)) == 7
    times = [e["at"] for e in everything]
    assert times == sorted(times, reverse=True)

    # An exact multiple of the page size ends with no dangling cursor.
    exact = _feed(client, group_id, limit=7).json()
    assert exact["next_before"] is None


def test_a_foreign_or_unknown_cursor_is_refused(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    assert _feed(client, group_id, before="act_doesnotexist").status_code == 422

    _onboard(client, "senior-2", "senior", "Mr Goh")
    _onboard(client, "family-z", "family", "Zed")
    pin = client.post("/v1/me/link-pin", headers=_headers("senior-2")).json()["pin"]
    other_group = client.post(
        "/v1/groups",
        json={"senior_pin": pin, "relationship": "Son"},
        headers=_headers("family-z"),
    ).json()["group_id"]
    foreign = _entries(client, other_group, "family-z")[0]["activity_id"]
    assert _feed(client, group_id, before=foreign).status_code == 422


# ── Check-ins ─────────────────────────────────────────────────────────────────


def test_a_check_in_is_recorded_with_its_note_and_who_made_it(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    _member_b(client, group_id)
    created = client.post(
        f"/v1/groups/{group_id}/check-ins",
        json={"kind": "called", "note": "  She sounded cheerful  "},
        headers=_headers(OWNER),
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["kind"] == "check_in"
    assert entry["check_in_kind"] == "called"
    assert entry["note"] == "She sounded cheerful"
    assert entry["is_me"] is True and entry["actor_name"] == "Wei Ling"

    seen_by_jun = _entries(client, group_id, "family-b")[0]
    assert seen_by_jun["activity_id"] == entry["activity_id"]
    assert seen_by_jun["is_me"] is False


def test_a_blank_note_is_stored_as_none(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    created = client.post(
        f"/v1/groups/{group_id}/check-ins",
        json={"kind": "visited", "note": "   \n "},
        headers=_headers(OWNER),
    )
    assert created.status_code == 201
    assert created.json()["note"] is None
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        row = session.get(FamilyActivityRow, created.json()["activity_id"])
        assert row is not None and row.note is None


def test_check_in_input_is_validated(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    path = f"/v1/groups/{group_id}/check-ins"
    owner = _headers(OWNER)
    assert client.post(path, json={"kind": "waved"}, headers=owner).status_code == 422
    assert client.post(path, json={}, headers=owner).status_code == 422
    too_long = client.post(path, json={"kind": "called", "note": "x" * 201}, headers=owner)
    assert too_long.status_code == 422
    assert (
        client.post(path, json={"kind": "called", "note": "x" * 200}, headers=owner).status_code
        == 201
    )
    # Spaces around a 200-character note are trimmed before the limit applies.
    padded = client.post(path, json={"kind": "called", "note": f" {'y' * 200} "}, headers=owner)
    assert padded.status_code == 201
    assert len(_entries(client, group_id)) == 3  # created + two check-ins


def test_check_ins_stay_out_of_the_calendar_the_senior_and_the_audit_trail(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    repository = client.app.state.repository  # type: ignore[attr-defined]
    with repository.sessions() as session:
        audit_before = session.scalar(select(func.count()).select_from(AuditEventRow))
    calendar_before = client.get(f"/v1/people/{person_id}/calendar", headers=_headers(OWNER)).json()
    state_before = client.get(f"/v1/people/{person_id}/state", headers=_headers(OWNER)).json()

    secret = "private-note-text"
    client.post(
        f"/v1/groups/{group_id}/check-ins",
        json={"kind": "called", "note": secret},
        headers=_headers(OWNER),
    )

    calendar_after = client.get(f"/v1/people/{person_id}/calendar", headers=_headers(OWNER)).json()
    state_after = client.get(f"/v1/people/{person_id}/state", headers=_headers(OWNER)).json()
    assert calendar_after == calendar_before
    assert state_after == state_before
    assert (
        secret
        not in client.get(f"/v1/people/{person_id}/calendar", headers=_headers("senior-1")).text
    )
    with repository.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == audit_before


def test_the_feed_names_a_member_without_an_account_as_a_family_member(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    _member_b(client, group_id)
    client.post(
        f"/v1/groups/{group_id}/check-ins", json={"kind": "called"}, headers=_headers("family-b")
    )
    with client.app.state.repository.sessions.begin() as session:  # type: ignore[attr-defined]
        account = session.get(AccountRow, "family-b")
        assert account is not None
        session.delete(account)
    latest = _entries(client, group_id)[0]
    assert (latest["kind"], latest["actor_name"]) == ("check_in", "Family member")


# ── Sign-in off (the offline demo) ────────────────────────────────────────────


@pytest.fixture
def demo(repo: SqlAlchemyRepository):  # noqa: F811
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    with TestClient(create_app(repo, settings=settings, migrate_on_start=False)) as test_client:
        yield test_client


def _demo_group(demo: TestClient) -> str:
    return demo.get("/v1/me").json()["groups"][0]["group_id"]


def test_the_demo_senior_is_not_a_member_so_the_feed_is_404(demo: TestClient) -> None:
    group_id = _demo_group(demo)
    senior = {"X-Demo-Sub": "demo-senior"}
    assert demo.get(f"/v1/groups/{group_id}/activity", headers=senior).status_code == 404
    assert (
        demo.post(
            f"/v1/groups/{group_id}/check-ins", json={"kind": "called"}, headers=senior
        ).status_code
        == 404
    )


def _demo_summary(demo: TestClient, group_id: str) -> list[tuple]:
    body = demo.get(f"/v1/groups/{group_id}/activity", params={"limit": 50}).json()
    return sorted(
        (e["kind"], e["actor_name"], e["appointment_title"], e["check_in_kind"], e["note"])
        for e in body["entries"]
    )


def test_a_demo_reset_leaves_exactly_the_seeded_entries_and_is_idempotent(
    demo: TestClient,
) -> None:
    group_id = _demo_group(demo)
    body = demo.get(f"/v1/groups/{group_id}/activity", params={"limit": 50}).json()
    assert len(body["entries"]) == 6
    assert {e["origin"] for e in body["entries"]} == {"demo_seed"}
    times = [e["at"] for e in body["entries"]]
    assert times == sorted(times, reverse=True) and len(set(times)) == 6
    assert max(times) < datetime.now(UTC).isoformat()
    kinds = {e["kind"] for e in body["entries"]}
    assert kinds == {"check_in", "helper_joined", "availability_updated", "note_added"}
    called = next(e for e in body["entries"] if e["check_in_kind"] == "called")
    assert (called["actor_name"], called["note"]) == ("Sarah", "She sounded cheerful")
    physio = next(e for e in body["entries"] if e["appointment_title"] == "Physiotherapy session")
    assert physio["actor_name"] == "Sarah" and physio["occurrence_id"] is not None
    seeded = _demo_summary(demo, group_id)

    # Live activity is cleared by a reset, and the seed comes back the same.
    demo.post(f"/v1/groups/{group_id}/check-ins", json={"kind": "messaged", "note": "hello"})
    assert len(_demo_summary(demo, group_id)) == 7
    for _ in range(2):
        assert demo.post("/v1/demo/reset").status_code == 200
        assert _demo_summary(demo, group_id) == seeded
        again = demo.get(f"/v1/groups/{group_id}/activity", params={"limit": 50}).json()
        assert {e["origin"] for e in again["entries"]} == {"demo_seed"}


def test_a_demo_reset_clears_entries_by_members_who_are_removed(demo: TestClient) -> None:
    group_id = _demo_group(demo)
    newcomer = {"X-Demo-Sub": "demo-family-2"}
    pin = demo.post(f"/v1/groups/{group_id}/join-pin").json()["pin"]
    demo.post("/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=newcomer)
    group = demo.get(f"/v1/groups/{group_id}").json()
    pending = next(m for m in group["members"] if m["status"] == "pending")
    demo.post(f"/v1/groups/{group_id}/members/{pending['member_id']}/approve")
    demo.post(f"/v1/groups/{group_id}/check-ins", json={"kind": "visited"}, headers=newcomer)
    # The reset removes the newcomer; their feed rows must go first (the foreign key).
    assert demo.post("/v1/demo/reset").status_code == 200
    assert len(_demo_summary(demo, group_id)) == 6


# ── Boundaries ────────────────────────────────────────────────────────────────


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += [node.module or ""] + [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def test_the_feed_imports_nothing_from_the_decision_path() -> None:
    forbidden = ("policy", "agent", "learning", "review_")
    for name in _imports(_SOURCE / "family_activity.py"):
        parts = name.split(".")
        leaf = parts[1] if parts[0] == "silverloop" and len(parts) > 1 else parts[0]
        assert not leaf.startswith(forbidden), name


def test_nothing_on_the_decision_path_imports_the_feed() -> None:
    for package in ("policy.py", "review_threshold.py", "agent"):
        target = _SOURCE / package
        files = [target] if target.is_file() else sorted(target.rglob("*.py"))
        assert files
        for path in files:
            assert not any("family_activity" in name for name in _imports(path)), path


def test_the_private_demo_helpers_never_record() -> None:
    """`_answer`, `_volunteer` and `_step_back` seed the demo and run inside public methods, which
    decide what is news; they must not write the feed themselves."""
    tree = ast.parse((_SOURCE / "family_calendar.py").read_text(encoding="utf-8"))
    private = {"_answer", "_volunteer", "_step_back"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in private:
            found.add(node.name)
            calls = {
                (
                    call.func.id
                    if isinstance(call.func, ast.Name)
                    else getattr(call.func, "attr", "")
                )
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
            assert not calls & {"record", "record_availability_updated"}, node.name
    assert found == private
