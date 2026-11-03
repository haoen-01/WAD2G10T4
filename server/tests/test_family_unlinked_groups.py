"""A family group can exist before its senior is linked (ADR 0010, issue #14).

A family member creates the group with the senior's name; an active member links the senior later
with the senior-link PIN, which is the senior's agreement. Until then the group sees nothing about
any senior. Foreign keys are enforced (the `repo` fixture from `test_family_activity`), so the demo
reset's delete order is checked here as on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from silverloop import family_groups
from silverloop.db_models import CareGroupRow, FamilyPinRow, PinAttemptRow
from silverloop.family_groups import SENIOR_LINK_TTL
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_family_activity import repo  # noqa: F401 - pytest fixture (foreign keys on)
from tests.test_family_calendar import demo  # noqa: F401 - pytest fixture
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
    _onboard,
    _senior_pin,
    client,  # noqa: F401 - pytest fixture
)

OWNER = "family-a"


def _create_unlinked(
    client: TestClient,  # noqa: F811
    sub: str = OWNER,
    name: str = "Mdm Tan",
    display_name: str = "Wei Ling",
) -> dict:
    _onboard(client, sub, "family", display_name)
    response = client.post(
        "/v1/groups",
        json={"senior_name": name, "relationship": "Daughter"},
        headers=_headers(sub),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _link(client: TestClient, group_id: str, pin: str, sub: str = OWNER):  # noqa: F811
    return client.post(
        f"/v1/groups/{group_id}/link-senior", json={"senior_pin": pin}, headers=_headers(sub)
    )


def _kinds(client: TestClient, group_id: str, sub: str = OWNER) -> list[str]:  # noqa: F811
    response = client.get(f"/v1/groups/{group_id}/activity?limit=50", headers=_headers(sub))
    assert response.status_code == 200, response.text
    return [entry["kind"] for entry in reversed(response.json()["entries"])]


def _add_member(client: TestClient, group_id: str, sub: str, *, approve: bool) -> str:  # noqa: F811
    _onboard(client, sub, "family", sub.title())
    joined = client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers(sub),
    )
    assert joined.status_code == 200, joined.text
    group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
    member_id = next(m["member_id"] for m in group["members"] if m["status"] == "pending")
    if approve:
        approved = client.post(
            f"/v1/groups/{group_id}/members/{member_id}/approve", headers=_headers(OWNER)
        )
        assert approved.status_code == 200, approved.text
    return member_id


def _pin_used(repo: SqlAlchemyRepository) -> bool:  # noqa: F811
    with repo.sessions() as session:
        return (
            session.scalar(
                select(FamilyPinRow.used_at).where(FamilyPinRow.purpose == "senior_link")
            )
            is not None
        )


def _attempts(repo: SqlAlchemyRepository) -> int:  # noqa: F811
    with repo.sessions() as session:
        return session.scalar(select(func.count()).select_from(PinAttemptRow)) or 0


# ── AC1-3: creating a group with only the senior's name ───────────────────────


def test_a_group_created_with_only_a_name_has_no_senior_and_an_active_owner(
    client: TestClient,  # noqa: F811
) -> None:
    group = _create_unlinked(client, name="  Mdm Tan  ")
    assert group["person_id"] is None
    assert group["senior_name"] == "Mdm Tan"
    [owner] = group["members"]
    assert (owner["role"], owner["status"], owner["is_me"]) == ("owner", "active", True)
    assert _kinds(client, group["group_id"]) == ["group_created"]


def test_creating_a_group_needs_the_seniors_name_or_their_pin(
    client: TestClient,  # noqa: F811
) -> None:
    _onboard(client, OWNER, "family", "Wei Ling")
    for body in (
        {"relationship": "Daughter"},
        {"relationship": "Daughter", "senior_name": "   "},
        {"relationship": "Daughter", "senior_name": "x" * 81},
        {"relationship": "Daughter", "senior_name": None, "senior_pin": None},
    ):
        response = client.post("/v1/groups", json=body, headers=_headers(OWNER))
        assert response.status_code == 422, body


def test_with_a_pin_the_seniors_own_account_name_wins_over_a_typed_one(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    _onboard(client, "senior-1", "senior", "Mdm Tan Ah Lian")
    _onboard(client, OWNER, "family", "Wei Ling")
    response = client.post(
        "/v1/groups",
        json={
            "senior_name": "Ma",
            "senior_pin": _senior_pin(client, "senior-1"),
            "relationship": "Daughter",
        },
        headers=_headers(OWNER),
    )
    assert response.status_code == 201, response.text
    group = response.json()
    assert group["person_id"] is not None
    assert group["senior_name"] == "Mdm Tan Ah Lian"
    with repo.sessions() as session:
        row = session.get(CareGroupRow, group["group_id"])
        assert row is not None
        assert row.senior_name == "Mdm Tan Ah Lian"
        assert (row.linked_via, row.linked_by) == ("senior_link_pin", OWNER)
        assert row.linked_at is not None


def test_me_lists_a_group_with_no_senior_linked(client: TestClient) -> None:  # noqa: F811
    group = _create_unlinked(client)
    me = client.get("/v1/me", headers=_headers(OWNER)).json()
    assert me["groups"] == [
        {
            "group_id": group["group_id"],
            "person_id": None,
            "senior_name": "Mdm Tan",
            "my_role": "owner",
            "my_status": "active",
            "member_count": 1,
            "last_opened": True,
            "unread_count": 0,
        }
    ]


def test_a_family_member_can_create_several_unlinked_groups(
    client: TestClient,  # noqa: F811
) -> None:
    first = _create_unlinked(client, name="Mdm Tan")
    second = client.post(
        "/v1/groups",
        json={"senior_name": "Mr Lee", "relationship": "Nephew"},
        headers=_headers(OWNER),
    )
    assert second.status_code == 201, second.text
    me = client.get("/v1/me", headers=_headers(OWNER)).json()
    assert [g["group_id"] for g in me["groups"]] == [first["group_id"], second.json()["group_id"]]


# ── AC4: linking the senior ───────────────────────────────────────────────────


def test_linking_the_senior_sets_the_person_shows_their_name_and_records_one_entry(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group = _create_unlinked(client, name="Ma")
    group_id = group["group_id"]
    _add_member(client, group_id, "family-b", approve=True)
    me = _onboard(client, "senior-1", "senior", "Mdm Tan Ah Lian")

    # Any active member may link, not only the owner.
    linked = _link(client, group_id, _senior_pin(client, "senior-1"), sub="family-b")
    assert linked.status_code == 200, linked.text
    assert linked.json()["person_id"] == me["person_id"]
    assert linked.json()["senior_name"] == "Mdm Tan Ah Lian"
    assert client.get("/v1/me", headers=_headers(OWNER)).json()["groups"][0]["senior_name"] == (
        "Mdm Tan Ah Lian"
    )
    assert _kinds(client, group_id).count("senior_linked") == 1
    assert _kinds(client, group_id)[-1] == "senior_linked"
    assert _pin_used(repo)
    with repo.sessions() as session:
        row = session.get(CareGroupRow, group_id)
        assert row is not None
        assert (row.linked_via, row.linked_by) == ("senior_link_pin", "family-b")
        # The typed name is kept, but only the senior's own name is shown.
        assert row.senior_name == "Ma"

    # Now linked, the group reads the senior's activity like any other.
    state = client.get(f"/v1/people/{me['person_id']}/state", headers=_headers(OWNER))
    assert state.status_code == 200, state.text


# ── AC5: link-senior refusals ─────────────────────────────────────────────────


def test_link_senior_is_404_for_pending_members_and_outsiders_before_any_pin_is_looked_at(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    pin = _senior_pin(client, "senior-1")
    before = _attempts(repo)
    for sub in ("family-b", "outsider"):
        assert _link(client, group_id, pin, sub=sub).status_code == 404
    assert _link(client, "grp_does_not_exist", pin, sub="outsider").status_code == 404
    # No PIN was tried for them, so the route cannot be used to guess PINs.
    assert _attempts(repo) == before
    assert not _pin_used(repo)
    assert _link(client, group_id, pin).status_code == 200


def test_a_wrong_pin_is_400_and_counts_toward_the_lockout(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    real = _senior_pin(client, "senior-1")
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        response = _link(client, group_id, wrong)
        assert response.status_code == 400
        assert "not right" in response.json()["detail"]
    assert _link(client, group_id, real).status_code == 429


def test_an_expired_pin_is_400(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    pin = _senior_pin(client, "senior-1")
    later = datetime.now(UTC) + SENIOR_LINK_TTL + timedelta(seconds=1)
    monkeypatch.setattr(family_groups, "_utcnow", lambda: later)
    response = _link(client, group_id, pin)
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_a_group_with_a_senior_refuses_and_the_same_pin_still_links_another_group(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    linked_group = _group_with_owner(client)  # family-a's group for senior-1 (Mdm Tan)
    _onboard(client, "senior-2", "senior", "Mr Goh")
    pin = _senior_pin(client, "senior-2")

    refused = _link(client, linked_group, pin)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "This family group already has a senior."
    assert not _pin_used(repo)
    assert "senior_linked" not in _kinds(client, linked_group)

    other = _create_unlinked(client, sub="family-c", name="Uncle Goh", display_name="Mei")
    relinked = _link(client, other["group_id"], pin, sub="family-c")
    assert relinked.status_code == 200, relinked.text
    assert relinked.json()["senior_name"] == "Mr Goh"


def test_a_senior_already_in_a_group_is_refused_without_naming_that_group(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    existing = _group_with_owner(client)  # senior-1 is in family-a's group
    other = _create_unlinked(client, sub="family-c", name="Ma", display_name="Mei")
    refused = _link(client, other["group_id"], _senior_pin(client, "senior-1"), sub="family-c")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail == (
        "This senior already has a family group. Ask one of its members for the join PIN."
    )
    assert existing not in refused.text and "Wei Ling" not in refused.text
    assert not _pin_used(repo)
    group = client.get(f"/v1/groups/{other['group_id']}", headers=_headers("family-c")).json()
    assert group["person_id"] is None
    assert _kinds(client, other["group_id"], sub="family-c") == ["group_created"]


def test_seniors_get_403_from_the_family_only_group_routes(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    senior = _headers("senior-1")
    assert (
        client.post(
            f"/v1/groups/{group_id}/link-senior", json={"senior_pin": "123456"}, headers=senior
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/v1/groups/{group_id}/senior-name", json={"senior_name": "X"}, headers=senior
        ).status_code
        == 403
    )
    assert client.get(f"/v1/groups/{group_id}/calendar", headers=senior).status_code == 403


# ── AC6: fixing the typed name ────────────────────────────────────────────────


def test_renaming_while_unlinked_changes_the_name_and_records_senior_renamed(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client, name="Mdm Tna")["group_id"]
    _add_member(client, group_id, "family-b", approve=True)
    renamed = client.put(
        f"/v1/groups/{group_id}/senior-name",
        json={"senior_name": "  Mdm Tan "},
        headers=_headers("family-b"),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["senior_name"] == "Mdm Tan"
    assert client.get("/v1/me", headers=_headers(OWNER)).json()["groups"][0]["senior_name"] == (
        "Mdm Tan"
    )
    assert _kinds(client, group_id)[-1] == "senior_renamed"
    for bad in ("", "   ", "x" * 81):
        response = client.put(
            f"/v1/groups/{group_id}/senior-name",
            json={"senior_name": bad},
            headers=_headers(OWNER),
        )
        assert response.status_code == 422, bad


def test_renaming_is_404_for_pending_members_and_outsiders(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("family-b", "outsider"):
        response = client.put(
            f"/v1/groups/{group_id}/senior-name",
            json={"senior_name": "Someone"},
            headers=_headers(sub),
        )
        assert response.status_code == 404
    assert "senior_renamed" not in _kinds(client, group_id)


def test_renaming_once_linked_is_409_naming_the_seniors_account(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client, name="Ma")["group_id"]
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    assert _link(client, group_id, _senior_pin(client, "senior-1")).status_code == 200
    response = client.put(
        f"/v1/groups/{group_id}/senior-name",
        json={"senior_name": "Grandma"},
        headers=_headers(OWNER),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "The name now comes from Mdm Tan's own account."
    assert "senior_renamed" not in _kinds(client, group_id)


# ── AC7: the group calendar ───────────────────────────────────────────────────


def test_the_group_calendar_works_before_the_senior_is_linked(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=True)
    day = date.today() + timedelta(days=3)
    created = client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Dentist",
            "kind": "medical",
            "date": day.isoformat(),
            "start": "10:00",
            "end": "11:00",
            "notes": "Bring the referral letter.",
        },
        headers=_headers(OWNER),
    )
    assert created.status_code == 201, created.text
    occurrence = f"{created.json()['appointment_id']}@{day.isoformat()}"
    assert (
        client.post(
            f"/v1/groups/{group_id}/helpers",
            json={"occurrence_id": occurrence},
            headers=_headers("family-b"),
        ).status_code
        == 204
    )
    assert (
        client.post(
            f"/v1/groups/{group_id}/availability",
            json={"date": day.isoformat(), "start": "09:00", "end": "12:00", "status": "available"},
            headers=_headers(OWNER),
        ).status_code
        == 201
    )
    note = client.post(
        f"/v1/groups/{group_id}/appointments/{created.json()['appointment_id']}/notes",
        json={"date": day.isoformat(), "text": "I can drive."},
        headers=_headers(OWNER),
    )
    assert note.status_code == 201, note.text

    response = client.get(f"/v1/groups/{group_id}/calendar", headers=_headers("family-b"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["person_id"] is None
    assert body["senior_name"] == "Mdm Tan"
    assert body["group_id"] == group_id
    assert [m["display_name"] for m in body["members"]] == ["Wei Ling", "Family-B"]
    [appointment] = body["appointments"]
    assert appointment["occurrence_id"] == occurrence
    assert appointment["notes"] == "Bring the referral letter."
    assert [a["occurrence_id"] for a in body["assignments"]] == [occurrence]
    assert {e["status"] for e in body["availability"]} == {"available"}
    notes = client.get(
        f"/v1/groups/{group_id}/appointments/{created.json()['appointment_id']}/notes",
        params={"date": day.isoformat()},
        headers=_headers("family-b"),
    )
    assert [n["text"] for n in notes.json()] == ["I can drive."]

    ranged = client.get(
        f"/v1/groups/{group_id}/calendar",
        params={"from_date": day.isoformat(), "to_date": day.isoformat()},
        headers=_headers(OWNER),
    )
    assert len(ranged.json()["appointments"]) == 1
    too_long = client.get(
        f"/v1/groups/{group_id}/calendar",
        params={"from_date": "2026-01-01", "to_date": "2027-12-31"},
        headers=_headers(OWNER),
    )
    assert too_long.status_code == 422


def test_the_group_calendar_is_404_for_pending_members_and_outsiders(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("family-b", "outsider"):
        assert (
            client.get(f"/v1/groups/{group_id}/calendar", headers=_headers(sub)).status_code == 404
        )


def test_a_linked_groups_calendar_matches_the_seniors_own(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    by_group = client.get(f"/v1/groups/{group_id}/calendar", headers=_headers(OWNER)).json()
    by_person = client.get(f"/v1/people/{person_id}/calendar", headers=_headers(OWNER)).json()
    assert by_group == by_person
    assert by_group["person_id"] == person_id
    assert by_group["senior_name"] == "Mdm Tan"


def test_a_member_of_an_unlinked_group_reads_nothing_about_any_senior(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client, name="Mdm Tan")["group_id"]
    other_senior = _onboard(client, "senior-1", "senior", "Mdm Ong")["person_id"]
    family = _headers(OWNER)
    for person_id in ("mdm-lim", other_senior):
        for path in ("state", "metrics", "wearable", "calendar"):
            response = client.get(f"/v1/people/{person_id}/{path}", headers=family)
            assert response.status_code == 404, (person_id, path)
    calendar = client.get(f"/v1/groups/{group_id}/calendar", headers=family)
    assert calendar.status_code == 200
    assert calendar.json()["person_id"] is None
    assert "Lim" not in calendar.text and "mdm-lim" not in calendar.text
    assert "Ong" not in calendar.text


# ── AC8: joining and approval on an unlinked group ────────────────────────────


def test_joining_approving_and_declining_work_on_an_unlinked_group(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _onboard(client, "family-b", "family", "Jun")
    pin = _join_pin(client, group_id)
    joined = client.post(
        "/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=_headers("family-b")
    )
    assert joined.status_code == 200, joined.text
    assert joined.json() == {
        "group_id": group_id,
        "person_id": None,
        "senior_name": "Mdm Tan",
        "my_role": "member",
        "my_status": "pending",
        "member_count": 1,
        "last_opened": False,
        "unread_count": 0,
    }
    group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
    pending = next(m for m in group["members"] if m["status"] == "pending")
    declined = client.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/decline", headers=_headers(OWNER)
    )
    assert declined.status_code == 200

    again = client.post(
        "/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=_headers("family-b")
    )
    assert again.status_code == 200
    group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
    pending = next(m for m in group["members"] if m["status"] == "pending")
    approved = client.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/approve", headers=_headers(OWNER)
    )
    assert approved.status_code == 200
    assert approved.json()["person_id"] is None
    assert {m["status"] for m in approved.json()["members"]} == {"active"}
    assert _kinds(client, group_id) == [
        "group_created",
        "member_declined",
        "member_approved",
    ]


# ── Sign-in off (the offline demo) ────────────────────────────────────────────


def test_the_demo_reset_removes_unlinked_groups_a_demo_account_created(
    demo: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    created = demo.post("/v1/groups", json={"senior_name": "Mr Ong", "relationship": "Son"})
    assert created.status_code == 201, created.text
    group_id = created.json()["group_id"]
    day = date.today() + timedelta(days=2)
    appointment = demo.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Haircut",
            "kind": "errand",
            "date": day.isoformat(),
            "start": "09:00",
            "end": "10:00",
        },
    ).json()
    demo.post(
        f"/v1/groups/{group_id}/appointments/{appointment['appointment_id']}/notes",
        json={"date": day.isoformat(), "text": "Short trim"},
    )
    demo.post(
        f"/v1/groups/{group_id}/helpers",
        json={"occurrence_id": f"{appointment['appointment_id']}@{day.isoformat()}"},
    )
    demo.post(f"/v1/groups/{group_id}/check-ins", json={"kind": "called"})
    demo.post(f"/v1/groups/{group_id}/join-pin")
    # Someone else's unlinked group is left alone.
    kept = demo.post(
        "/v1/groups",
        json={"senior_name": "Mdm Koh", "relationship": "Son"},
        headers={"X-Demo-Sub": "someone-else"},
    ).json()["group_id"]
    assert [g["group_id"] for g in demo.get("/v1/me").json()["groups"]][-1] == group_id

    assert demo.post("/v1/demo/reset").status_code == 200
    groups = demo.get("/v1/me").json()["groups"]
    assert [g["person_id"] for g in groups] == ["mdm-lim"]
    with repo.sessions() as session:
        assert session.get(CareGroupRow, group_id) is None
        assert session.get(CareGroupRow, kept) is not None


def test_the_demo_reset_takes_the_demo_family_out_of_unlinked_groups_they_joined(
    demo: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    someone = {"X-Demo-Sub": "someone-else"}
    created = demo.post(
        "/v1/groups", json={"senior_name": "Mdm Koh", "relationship": "Son"}, headers=someone
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group_id"]
    pin = demo.post(f"/v1/groups/{group_id}/join-pin", headers=someone).json()["pin"]
    joined = demo.post("/v1/groups/join", json={"pin": pin, "relationship": "Friend"})
    assert joined.status_code == 200, joined.text
    pending = next(
        m
        for m in demo.get(f"/v1/groups/{group_id}", headers=someone).json()["members"]
        if m["status"] == "pending"
    )
    approved = demo.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/approve", headers=someone
    )
    assert approved.status_code == 200, approved.text
    # Sarah leaves a trace in that group too: a check-in and a shared free time.
    demo.post(f"/v1/groups/{group_id}/check-ins", json={"kind": "called"})
    day = (date.today() + timedelta(days=1)).isoformat()
    demo.post(
        f"/v1/groups/{group_id}/availability",
        json={"date": day, "start": "09:00", "end": "10:00", "status": "available"},
    )
    before = [(g["person_id"], g["my_status"]) for g in demo.get("/v1/me").json()["groups"]]
    assert before == [("mdm-lim", "active"), (None, "active")]

    assert demo.post("/v1/demo/reset").status_code == 200
    after = [(g["person_id"], g["my_status"]) for g in demo.get("/v1/me").json()["groups"]]
    assert after == [("mdm-lim", "active")]
    # The other family's group stays, with its own member.
    group = demo.get(f"/v1/groups/{group_id}", headers=someone).json()
    assert [m["is_me"] for m in group["members"]] == [True]
    with repo.sessions() as session:
        assert session.get(CareGroupRow, group_id) is not None


def test_two_groups_racing_to_link_one_senior_get_409_and_the_pin_stays_unused(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _create_unlinked(client, name="Ma")["group_id"]
    second = _create_unlinked(client, sub="family-c", name="Mum", display_name="Mei")["group_id"]
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    assert _link(client, first, _senior_pin(client, "senior-1")).status_code == 200
    pin = _senior_pin(client, "senior-1")

    # The other group's link committed after this one's check: the check sees no group, and only
    # the unique `person_id` stops the second link.
    real_scalar = family_groups.Session.scalar

    def scalar_missing_the_other_group(self, statement, *args, **kwargs):  # noqa: ANN001
        text_of = str(statement)
        if "care_groups.group_id" in text_of and "care_groups.person_id =" in text_of:
            return None
        return real_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(family_groups.Session, "scalar", scalar_missing_the_other_group)
    raced = _link(client, second, pin, sub="family-c")
    monkeypatch.undo()

    assert raced.status_code == 409
    assert "already has a family group" in raced.json()["detail"]
    assert not _pin_used(repo)
    with repo.sessions() as session:
        row = session.get(CareGroupRow, second)
        assert row is not None and row.person_id is None
    assert _kinds(client, second, sub="family-c") == ["group_created"]
