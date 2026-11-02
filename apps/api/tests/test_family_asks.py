"""Asking a helper and notifications (issue #16): every move of an ask, who may make it, who is
told, and that nothing else moves it.

Foreign keys are enforced (the `repo` fixture from `test_family_activity`), so the demo reset's
delete order is checked here as on PostgreSQL.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from silverloop import family_asks
from silverloop.db_models import AppointmentRow, HelperAskRow, NotificationRow
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.local_time import at_local, local_date
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_family_activity import repo  # noqa: F401 - pytest fixture (foreign keys on)
from tests.test_family_calendar import _member_b, demo  # noqa: F401 - pytest fixture
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
    _onboard,
    client,  # noqa: F401 - pytest fixture
)

_SOURCE = Path(__file__).resolve().parents[1] / "src" / "silverloop"
OWNER = "family-a"  # Wei Ling
B = "family-b"  # Jun
C = "family-c"  # Kai


# ── Helpers ───────────────────────────────────────────────────────────────────


def _today() -> date:
    return local_date(datetime.now(UTC))


def _member_c(client: TestClient, group_id: str, *, approve: bool = True) -> None:  # noqa: F811
    _onboard(client, C, "family", "Kai")
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Nephew"},
        headers=_headers(C),
    )
    if approve:
        group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
        pending = next(m for m in group["members"] if m["status"] == "pending")
        client.post(
            f"/v1/groups/{group_id}/members/{pending['member_id']}/approve",
            headers=_headers(OWNER),
        )


def _family(client: TestClient) -> tuple[str, dict[str, str]]:  # noqa: F811
    """A group with Wei Ling (owner), Jun and Kai, all active; member ids by sub."""
    group_id = _group_with_owner(client)
    _member_b(client, group_id)
    _member_c(client, group_id)
    return group_id, _member_ids(client, group_id)


def _member_ids(client: TestClient, group_id: str) -> dict[str, str]:  # noqa: F811
    ids: dict[str, str] = {}
    for sub in (OWNER, B, C):
        group = client.get(f"/v1/groups/{group_id}", headers=_headers(sub))
        if group.status_code != 200:
            continue
        me = next(m for m in group.json()["members"] if m["is_me"])
        ids[sub] = me["member_id"]
    return ids


def _appointment(
    client: TestClient,  # noqa: F811
    group_id: str,
    day: date,
    *,
    start: str = "09:30",
    **changes: object,
) -> str:
    response = client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Physio",
            "kind": "therapy",
            "date": day.isoformat(),
            "start": start,
            "end": "23:00",
            **changes,
        },
        headers=_headers(OWNER),
    )
    assert response.status_code == 201, response.text
    return response.json()["appointment_id"]


def _occurrence(appointment_id: str, day: date) -> str:
    return f"{appointment_id}@{day.isoformat()}"


def _ask(client: TestClient, group_id: str, occurrence: str, asked: str, sub: str = OWNER):  # noqa: F811
    return client.post(
        f"/v1/groups/{group_id}/asks",
        json={"occurrence_id": occurrence, "asked_member_id": asked},
        headers=_headers(sub),
    )


def _open_ask(client: TestClient, group_id: str, occurrence: str, asked: str) -> dict:  # noqa: F811
    response = _ask(client, group_id, occurrence, asked)
    assert response.status_code == 201, response.text
    return response.json()


def _act(client: TestClient, group_id: str, ask_id: str, action: str, sub: str):  # noqa: F811
    return client.post(f"/v1/groups/{group_id}/asks/{ask_id}/{action}", headers=_headers(sub))


def _open_asks(client: TestClient, group_id: str, sub: str = OWNER) -> list[dict]:  # noqa: F811
    response = client.get(f"/v1/groups/{group_id}/asks", headers=_headers(sub))
    assert response.status_code == 200, response.text
    return response.json()["asks"]


def _inbox(client: TestClient, sub: str, **params: object) -> dict:  # noqa: F811
    response = client.get("/v1/me/notifications", params=params, headers=_headers(sub))
    assert response.status_code == 200, response.text
    return response.json()


def _kinds(client: TestClient, sub: str) -> list[str]:  # noqa: F811
    """Oldest first."""
    return [item["kind"] for item in reversed(_inbox(client, sub, limit=50)["items"])]


def _feed_kinds(client: TestClient, group_id: str) -> list[str]:  # noqa: F811
    body = client.get(
        f"/v1/groups/{group_id}/activity", params={"limit": 50}, headers=_headers(OWNER)
    ).json()
    return [e["kind"] for e in reversed(body["entries"])]


def _helpers(client: TestClient, group_id: str, occurrence: str) -> set[str]:  # noqa: F811
    day = occurrence.split("@")[1]
    body = client.get(
        f"/v1/groups/{group_id}/calendar",
        params={"from_date": day, "to_date": day},
        headers=_headers(OWNER),
    ).json()
    return {a["member_id"] for a in body["assignments"] if a["occurrence_id"] == occurrence}


def _state(repo: SqlAlchemyRepository, ask_id: str) -> str:  # noqa: F811
    with repo.sessions() as session:
        return session.get(HelperAskRow, ask_id).state


def _setup(client: TestClient, days: int = 10) -> tuple[str, dict[str, str], str]:  # noqa: F811
    """The family, and one future appointment day nobody is going to."""
    group_id, ids = _family(client)
    day = _today() + timedelta(days=days)
    return group_id, ids, _occurrence(_appointment(client, group_id, day), day)


# ── Asking ────────────────────────────────────────────────────────────────────


def test_asking_opens_an_ask_tells_only_the_asked_member_and_writes_one_feed_line(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    assert ask["state"] == "open"
    assert ask["occurrence_id"] == occurrence
    assert (ask["asker_member_id"], ask["asker_name"]) == (ids[OWNER], "Wei Ling")
    assert (ask["asked_member_id"], ask["asked_name"]) == (ids[B], "Jun")
    assert ask["can_withdraw"] is True and ask["can_answer"] is False

    assert _kinds(client, B) == ["ask_received"]
    assert _kinds(client, OWNER) == []
    assert _kinds(client, C) == []
    [item] = _inbox(client, B)["items"]
    assert item["group_label"] == "Mdm Tan"
    assert item["ask_id"] == ask["ask_id"] and item["ask_state"] == "open"
    assert item["appointment_title"] == "Physio" and item["start"] == "09:30"
    assert item["occurrence_id"] == occurrence
    assert (item["asker_name"], item["asked_name"], item["ended_by_name"]) == (
        "Wei Ling",
        "Jun",
        None,
    )
    assert item["is_open_for_me"] is True and item["read"] is False

    assert _feed_kinds(client, group_id)[-1] == "helper_asked"
    latest = client.get(f"/v1/groups/{group_id}/activity", headers=_headers(OWNER)).json()
    entry = latest["entries"][0]
    assert (entry["actor_name"], entry["subject_name"]) == ("Wei Ling", "Jun")
    assert entry["occurrence_id"] == occurrence

    # The day still needs a helper, and every member sees who was asked.
    assert _helpers(client, group_id, occurrence) == set()
    [seen_by_b] = _open_asks(client, group_id, B)
    assert seen_by_b["can_answer"] is True and seen_by_b["can_withdraw"] is False
    [seen_by_c] = _open_asks(client, group_id, C)
    assert seen_by_c["can_answer"] is False and seen_by_c["can_withdraw"] is False


def test_a_second_open_ask_for_the_same_day_is_409_and_a_new_one_follows_an_ending(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    first = _open_ask(client, group_id, occurrence, ids[B])
    again = _ask(client, group_id, occurrence, ids[C])
    assert again.status_code == 409
    assert again.json()["detail"] == "Someone has already been asked for this day"
    assert _ask(client, group_id, occurrence, ids[OWNER], sub=C).status_code == 409

    assert _act(client, group_id, first["ask_id"], "decline", B).status_code == 204
    second = _ask(client, group_id, occurrence, ids[C])
    assert second.status_code == 201, second.text
    assert [a["ask_id"] for a in _open_asks(client, group_id)] == [second.json()["ask_id"]]


def test_two_asks_racing_for_one_day_end_in_409_at_the_unique_index(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client)
    _open_ask(client, group_id, occurrence, ids[B])
    # The second request's check ran before the first committed.
    monkeypatch.setattr(family_asks, "open_ask", lambda *_args: None)
    raced = _ask(client, group_id, occurrence, ids[C])
    assert raced.status_code == 409
    assert raced.json()["detail"] == "Someone has already been asked for this day"
    assert len(_open_asks(client, group_id)) == 1
    assert _kinds(client, C) == []


def test_asks_that_are_refused_with_422(client: TestClient) -> None:  # noqa: F811
    group_id, ids, occurrence = _setup(client)
    other_group = client.post(
        "/v1/groups", json={"senior_name": "Mr Ong", "relationship": "Son"}, headers=_headers(C)
    ).json()["group_id"]
    outsider = next(
        m["member_id"]
        for m in client.get(f"/v1/groups/{other_group}", headers=_headers(C)).json()["members"]
    )
    cases = {
        ids[OWNER]: "You can't ask yourself",
        # The senior is never a member; nor is anyone unknown or in another group.
        "mem_senior": "Ask an active member of this family group",
        outsider: "Ask an active member of this family group",
    }
    for asked, detail in cases.items():
        response = _ask(client, group_id, occurrence, asked)
        assert response.status_code == 422, asked
        assert response.json()["detail"] == detail

    # A pending member cannot be asked either.
    _onboard(client, "family-d", "family", "Mei")
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Niece"},
        headers=_headers("family-d"),
    )
    pending = next(
        m["member_id"]
        for m in client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()["members"]
        if m["status"] == "pending"
    )
    assert _ask(client, group_id, occurrence, pending).status_code == 422

    # Someone already going, and so a day that no longer needs a helper.
    client.post(
        f"/v1/groups/{group_id}/helpers",
        json={"occurrence_id": occurrence},
        headers=_headers(B),
    )
    helping = _ask(client, group_id, occurrence, ids[B])
    assert (helping.status_code, helping.json()["detail"]) == (422, "They are already going")
    taken = _ask(client, group_id, occurrence, ids[C])
    assert (taken.status_code, taken.json()["detail"]) == (
        422,
        "This day no longer needs a helper",
    )
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        assert session.scalar(select(func.count()).select_from(HelperAskRow)) == 0
        assert session.scalar(select(func.count()).select_from(NotificationRow)) == 0


def test_a_day_that_has_started_cannot_be_asked_for(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client, days=3)
    day = date.fromisoformat(occurrence.split("@")[1])
    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 9, 30))
    response = _ask(client, group_id, occurrence, ids[B])
    assert (response.status_code, response.json()["detail"]) == (
        422,
        "This day has already started",
    )
    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 9, 29))
    assert _ask(client, group_id, occurrence, ids[B]).status_code == 201


def test_an_occurrence_the_appointment_does_not_have_is_404(client: TestClient) -> None:  # noqa: F811
    group_id, ids, occurrence = _setup(client)
    appointment_id, day = occurrence.split("@")
    wrong_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    assert _ask(client, group_id, f"{appointment_id}@{wrong_day}", ids[B]).status_code == 404
    assert _ask(client, group_id, f"appt_nothing@{day}", ids[B]).status_code == 404
    assert _ask(client, group_id, "not-an-occurrence", ids[B]).status_code == 404


# ── Yes, no, withdraw ─────────────────────────────────────────────────────────


def test_yes_makes_the_asked_member_the_helper_and_tells_the_asker(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    assert _act(client, group_id, ask["ask_id"], "accept", B).status_code == 204

    assert _state(repo, ask["ask_id"]) == "accepted"
    assert _helpers(client, group_id, occurrence) == {ids[B]}
    assert _open_asks(client, group_id) == []
    assert _kinds(client, OWNER) == ["ask_accepted"]
    assert _kinds(client, B) == ["ask_received"]
    assert _kinds(client, C) == []
    [told] = _inbox(client, OWNER)["items"]
    assert (told["ask_state"], told["ended_by_name"], told["is_open_for_me"]) == (
        "accepted",
        "Jun",
        False,
    )
    # The same feed line as "I'll go", by the asked member.
    assert _feed_kinds(client, group_id)[-2:] == ["helper_asked", "helper_joined"]
    latest = client.get(f"/v1/groups/{group_id}/activity", headers=_headers(OWNER)).json()
    assert latest["entries"][0]["actor_name"] == "Jun"
    # Ended asks never reopen.
    for action, sub in (("accept", B), ("decline", B), ("withdraw", OWNER)):
        again = _act(client, group_id, ask["ask_id"], action, sub)
        assert (again.status_code, again.json()["detail"]) == (409, "This ask has already ended")


def test_no_tells_the_asker_writes_a_feed_line_and_the_day_needs_a_helper_again(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    assert _act(client, group_id, ask["ask_id"], "decline", B).status_code == 204

    assert _state(repo, ask["ask_id"]) == "declined"
    assert _helpers(client, group_id, occurrence) == set()
    assert _open_asks(client, group_id) == []
    assert _kinds(client, OWNER) == ["ask_declined"]
    assert _kinds(client, B) == ["ask_received"]
    assert _feed_kinds(client, group_id)[-2:] == ["helper_asked", "helper_declined"]
    latest = client.get(f"/v1/groups/{group_id}/activity", headers=_headers(OWNER)).json()
    assert latest["entries"][0]["actor_name"] == "Jun"
    assert latest["entries"][0]["occurrence_id"] == occurrence
    [received] = _inbox(client, B)["items"]
    assert (received["ask_state"], received["is_open_for_me"]) == ("declined", False)


def test_withdrawing_tells_the_asked_member_and_writes_nothing_to_the_feed(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    feed_before = _feed_kinds(client, group_id)
    assert _act(client, group_id, ask["ask_id"], "withdraw", OWNER).status_code == 204

    assert _state(repo, ask["ask_id"]) == "withdrawn"
    assert _kinds(client, B) == ["ask_received", "ask_withdrawn"]
    assert _kinds(client, OWNER) == []
    assert _feed_kinds(client, group_id) == feed_before
    received = _inbox(client, B)["items"][1]
    assert received["kind"] == "ask_received"
    assert (received["ask_state"], received["is_open_for_me"]) == ("withdrawn", False)
    assert _inbox(client, B)["items"][0]["ended_by_name"] == "Wei Ling"


def test_only_the_asked_member_answers_and_only_the_asker_withdraws(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    for action, sub in (
        ("accept", OWNER),
        ("accept", C),
        ("decline", OWNER),
        ("decline", C),
        ("withdraw", B),
        ("withdraw", C),
    ):
        response = _act(client, group_id, ask["ask_id"], action, sub)
        assert response.status_code == 403, (action, sub)
    assert _state(repo, ask["ask_id"]) == "open"
    assert _kinds(client, OWNER) == []
    # The wrong actor is told so even once the ask has ended (403 before 409).
    _act(client, group_id, ask["ask_id"], "withdraw", OWNER)
    assert _act(client, group_id, ask["ask_id"], "accept", C).status_code == 403


def test_asks_are_for_active_members_only(client: TestClient) -> None:  # noqa: F811
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    _onboard(client, "outsider", "family", "Lee")
    _onboard(client, "family-d", "family", "Mei")
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Niece"},
        headers=_headers("family-d"),
    )
    for sub in ("outsider", "family-d"):
        assert _ask(client, group_id, occurrence, ids[B], sub=sub).status_code == 404
        assert client.get(f"/v1/groups/{group_id}/asks", headers=_headers(sub)).status_code == 404
        for action in ("accept", "decline", "withdraw"):
            assert _act(client, group_id, ask["ask_id"], action, sub).status_code == 404
    # An unknown group, and an ask that is not this group's.
    assert client.get("/v1/groups/grp_nothing/asks", headers=_headers(OWNER)).status_code == 404
    other = client.post(
        "/v1/groups", json={"senior_name": "Mr Ong", "relationship": "Son"}, headers=_headers(B)
    ).json()["group_id"]
    assert _act(client, other, ask["ask_id"], "accept", B).status_code == 404
    assert _act(client, group_id, "ask_nothing", "accept", B).status_code == 404
    # A senior gets 403 from every ask route and from the notifications.
    senior = _headers("senior-1")
    assert (
        client.post(
            f"/v1/groups/{group_id}/asks",
            json={"occurrence_id": occurrence, "asked_member_id": ids[B]},
            headers=senior,
        ).status_code
        == 403
    )
    assert client.get(f"/v1/groups/{group_id}/asks", headers=senior).status_code == 403
    for action in ("accept", "decline", "withdraw"):
        assert (
            client.post(
                f"/v1/groups/{group_id}/asks/{ask['ask_id']}/{action}", headers=senior
            ).status_code
            == 403
        )
    assert client.get("/v1/me/notifications", headers=senior).status_code == 403
    assert (
        client.post("/v1/me/notifications/read", json={"all": True}, headers=senior).status_code
        == 403
    )


def test_only_open_asks_can_be_listed(client: TestClient) -> None:  # noqa: F811
    group_id, _, _ = _setup(client)
    response = client.get(
        f"/v1/groups/{group_id}/asks", params={"state": "declined"}, headers=_headers(OWNER)
    )
    assert response.status_code == 422


# ── "I'll go" and the answers ─────────────────────────────────────────────────


def test_the_asked_members_ill_go_accepts_the_ask(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    client.post(
        f"/v1/groups/{group_id}/helpers", json={"occurrence_id": occurrence}, headers=_headers(B)
    )
    assert _state(repo, ask["ask_id"]) == "accepted"
    assert _kinds(client, OWNER) == ["ask_accepted"]
    assert _kinds(client, B) == ["ask_received"]
    assert _feed_kinds(client, group_id)[-1] == "helper_joined"


def test_someone_elses_ill_go_closes_the_ask_and_tells_the_asker_and_the_asked_member(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    client.post(
        f"/v1/groups/{group_id}/helpers", json={"occurrence_id": occurrence}, headers=_headers(C)
    )
    assert _state(repo, ask["ask_id"]) == "closed"
    assert _helpers(client, group_id, occurrence) == {ids[C]}
    assert _kinds(client, OWNER) == ["ask_closed"]
    assert _kinds(client, B) == ["ask_received", "ask_closed"]
    assert _kinds(client, C) == []
    assert _inbox(client, OWNER)["items"][0]["ended_by_name"] == "Kai"
    assert _open_asks(client, group_id) == []
    assert _act(client, group_id, ask["ask_id"], "accept", B).status_code == 409


def test_the_askers_own_ill_go_closes_the_ask_and_tells_only_the_asked_member(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    client.post(
        f"/v1/groups/{group_id}/helpers",
        json={"occurrence_id": occurrence},
        headers=_headers(OWNER),
    )
    assert _state(repo, ask["ask_id"]) == "closed"
    assert _kinds(client, OWNER) == []
    assert _kinds(client, B) == ["ask_received", "ask_closed"]


def test_nothing_else_moves_an_open_ask(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    """Answering "unavailable", stepping back, sharing free times, a check-in, a note, changing
    the appointment's details or time: the ask stays open and nobody is told."""
    group_id, ids, occurrence = _setup(client)
    appointment_id, day = occurrence.split("@")
    ask = _open_ask(client, group_id, occurrence, ids[B])
    for sub in (B, C):
        client.post(
            f"/v1/groups/{group_id}/answers",
            json={"occurrence_id": occurrence, "status": "unavailable"},
            headers=_headers(sub),
        )
        client.post(
            f"/v1/groups/{group_id}/helpers/step-back",
            json={"occurrence_id": occurrence},
            headers=_headers(sub),
        )
    client.post(
        f"/v1/groups/{group_id}/availability",
        json={"date": day, "start": "08:00", "end": "12:00", "status": "available"},
        headers=_headers(B),
    )
    client.post(f"/v1/groups/{group_id}/check-ins", json={"kind": "called"}, headers=_headers(B))
    client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/notes",
        json={"date": day, "text": "Bring the folder"},
        headers=_headers(C),
    )
    changed = client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json={
            "title": "Physio (new room)",
            "kind": "therapy",
            "date": day,
            "start": "11:00",
            "end": "23:00",
        },
        headers=_headers(OWNER),
    )
    assert changed.status_code == 200, changed.text
    assert _state(repo, ask["ask_id"]) == "open"
    assert _kinds(client, OWNER) == []
    assert _kinds(client, B) == ["ask_received"]
    [item] = _inbox(client, B)["items"]
    # The bell shows the appointment as it is now.
    assert (item["appointment_title"], item["start"]) == ("Physio (new room)", "11:00")


# ── Lapsing ───────────────────────────────────────────────────────────────────


def test_an_unanswered_ask_lapses_at_the_start_time_when_next_read_and_tells_the_asker_once(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client, days=2)
    day = date.fromisoformat(occurrence.split("@")[1])
    ask = _open_ask(client, group_id, occurrence, ids[B])

    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 9, 29))
    assert len(_open_asks(client, group_id)) == 1
    assert _state(repo, ask["ask_id"]) == "open"

    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 9, 30))
    # Reading the bell is enough: no scheduler.
    assert _kinds(client, OWNER) == ["ask_lapsed"]
    assert _state(repo, ask["ask_id"]) == "lapsed"
    for _ in range(3):
        assert _open_asks(client, group_id) == []
        assert _kinds(client, OWNER) == ["ask_lapsed"]
        assert _kinds(client, B) == ["ask_received"]
    lapsed = _inbox(client, OWNER)["items"][0]
    assert (lapsed["ask_state"], lapsed["ended_by_name"]) == ("lapsed", None)
    assert _act(client, group_id, ask["ask_id"], "accept", B).status_code == 409
    # Nothing in the feed for a lapse.
    assert _feed_kinds(client, group_id)[-1] == "helper_asked"


def test_an_ask_lapses_at_the_appointments_new_time_after_a_time_change(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client, days=2)
    appointment_id, day_text = occurrence.split("@")
    day = date.fromisoformat(day_text)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json={
            "title": "Physio",
            "kind": "therapy",
            "date": day_text,
            "start": "15:00",
            "end": "23:00",
        },
        headers=_headers(OWNER),
    )
    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 10, 0))
    assert len(_open_asks(client, group_id)) == 1
    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 15, 0))
    assert _open_asks(client, group_id) == []
    assert _state(repo, ask["ask_id"]) == "lapsed"


def test_an_ask_whose_day_has_started_lapses_before_an_ill_go_could_close_it(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client, days=2)
    day = date.fromisoformat(occurrence.split("@")[1])
    ask = _open_ask(client, group_id, occurrence, ids[B])
    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 12, 0))
    client.post(
        f"/v1/groups/{group_id}/helpers", json={"occurrence_id": occurrence}, headers=_headers(C)
    )
    assert _state(repo, ask["ask_id"]) == "lapsed"
    assert _kinds(client, OWNER) == ["ask_lapsed"]
    assert _kinds(client, B) == ["ask_received"]


def test_ending_an_ask_is_a_compare_and_set(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    now = datetime.now(UTC)
    with repo.sessions.begin() as session:
        row = session.get(HelperAskRow, ask["ask_id"])
        assert family_asks._end(session, row, family_asks.HelperAskState.LAPSED, by=None, at=now)
        # A second ending of the same ask changes nothing.
        assert not family_asks._end(
            session, row, family_asks.HelperAskState.ACCEPTED, by=ids[B], at=now
        )
    assert _state(repo, ask["ask_id"]) == "lapsed"


def test_a_due_ask_whose_appointment_is_gone_is_withdrawn_rather_than_lapsed(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delete hook normally withdraws it first; the lapse check does not rely on that."""
    group_id, ids, occurrence = _setup(client, days=2)
    appointment_id, day_text = occurrence.split("@")
    ask = _open_ask(client, group_id, occurrence, ids[B])
    with repo.sessions.begin() as session:
        session.delete(session.get(AppointmentRow, appointment_id))
    monkeypatch.setattr(
        family_asks, "_utcnow", lambda: at_local(date.fromisoformat(day_text), 12, 0)
    )
    assert _open_asks(client, group_id) == []
    assert _state(repo, ask["ask_id"]) == "withdrawn"
    assert _kinds(client, B) == ["ask_received", "ask_withdrawn"]
    assert _kinds(client, OWNER) == []
    assert _inbox(client, B)["items"][0]["ended_by_name"] is None


# ── The appointment day is removed ────────────────────────────────────────────


def test_deleting_the_appointment_withdraws_its_open_ask_and_the_notice_still_reads(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    appointment_id = occurrence.split("@")[0]
    ask = _open_ask(client, group_id, occurrence, ids[B])
    deleted = client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=_headers(C)
    )
    assert deleted.status_code == 204
    assert _state(repo, ask["ask_id"]) == "withdrawn"
    assert _kinds(client, B) == ["ask_received", "ask_withdrawn"]
    assert _kinds(client, OWNER) == [] and _kinds(client, C) == []
    for item in _inbox(client, B)["items"]:
        assert item["appointment_title"] == "Physio"  # the snapshot
        assert item["occurrence_id"] is None and item["start"] is None
        assert item["ask_state"] == "withdrawn" and item["is_open_for_me"] is False
    assert _inbox(client, B)["items"][0]["ended_by_name"] == "Kai"
    assert _open_asks(client, group_id) == []


def test_the_asked_member_removing_the_appointment_is_not_told_about_it(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    _open_ask(client, group_id, occurrence, ids[B])
    client.post(
        f"/v1/groups/{group_id}/appointments/{occurrence.split('@')[0]}/delete",
        headers=_headers(B),
    )
    assert _kinds(client, B) == ["ask_received"]


def test_deleting_after_the_start_with_no_read_in_between_lapses_the_ask_rather_than_withdrawing(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client, days=2)
    appointment_id, day_text = occurrence.split("@")
    ask = _open_ask(client, group_id, occurrence, ids[B])
    monkeypatch.setattr(
        family_asks, "_utcnow", lambda: at_local(date.fromisoformat(day_text), 23, 0)
    )
    deleted = client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=_headers(C)
    )
    assert deleted.status_code == 204
    assert _state(repo, ask["ask_id"]) == "lapsed"
    assert _kinds(client, OWNER) == ["ask_lapsed"]
    assert _kinds(client, B) == ["ask_received"]
    assert _kinds(client, C) == []


def test_an_edit_that_removes_a_started_day_lapses_the_ask_rather_than_withdrawing(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, ids, occurrence = _setup(client, days=2)
    appointment_id, day_text = occurrence.split("@")
    day = date.fromisoformat(day_text)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    monkeypatch.setattr(family_asks, "_utcnow", lambda: at_local(day, 23, 0))
    moved = client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json={
            "title": "Physio",
            "kind": "therapy",
            "date": (day + timedelta(days=1)).isoformat(),
            "start": "09:30",
            "end": "23:00",
        },
        headers=_headers(C),
    )
    assert moved.status_code == 200, moved.text
    assert _state(repo, ask["ask_id"]) == "lapsed"
    assert _kinds(client, OWNER) == ["ask_lapsed"]
    assert _kinds(client, B) == ["ask_received"]
    assert _kinds(client, C) == []


def test_the_appointment_is_locked_before_asks_are_read_or_ended(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asking, "I'll go", editing and deleting read the appointment `FOR UPDATE` first, so they
    run one at a time per appointment on PostgreSQL (SQLite has no row locks; SQLAlchemy leaves
    the clause out there)."""
    group_id, ids, occurrence = _setup(client)
    appointment_id, day = occurrence.split("@")
    real = FamilyCalendarStore._appointment
    locks: list[bool] = []

    def spy(session, group_id, appointment_id, *, lock=False):  # noqa: ANN001, ANN202
        locks.append(lock)
        return real(session, group_id, appointment_id, lock=lock)

    monkeypatch.setattr(FamilyCalendarStore, "_appointment", staticmethod(spy))
    calls = [
        lambda: _ask(client, group_id, occurrence, ids[B]),
        lambda: client.post(
            f"/v1/groups/{group_id}/helpers",
            json={"occurrence_id": occurrence},
            headers=_headers(C),
        ),
        lambda: client.put(
            f"/v1/groups/{group_id}/appointments/{appointment_id}",
            json={
                "title": "Physio",
                "kind": "therapy",
                "date": day,
                "start": "10:00",
                "end": "23:00",
            },
            headers=_headers(OWNER),
        ),
        lambda: client.post(
            f"/v1/groups/{group_id}/appointments/{appointment_id}/delete",
            headers=_headers(OWNER),
        ),
    ]
    for call in calls:
        locks.clear()
        response = call()
        assert response.status_code in (200, 201, 204), response.text
        assert locks[:1] == [True]


@pytest.mark.parametrize(
    ("action", "sub_key"),
    [("accept", "asked"), ("decline", "asked"), ("withdraw", "asker")],
)
def test_answering_an_ask_locks_the_appointment_before_any_ask_is_lapsed_or_ended(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    sub_key: str,
) -> None:
    """Accepting, declining and withdrawing keep the same lock order as asking, "I'll go", editing
    and deleting: the appointment `FOR UPDATE` first, then `lapse_due`, then the ask's own
    compare-and-set. Ending the ask first deadlocked against "I'll go" and delete on PostgreSQL
    (the helper rows' foreign key locks the appointment)."""
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    events: list[str] = []
    real_appointment = FamilyCalendarStore._appointment
    real_lapse = family_asks.lapse_due
    real_end = family_asks._end

    def appointment_spy(session, group_id, appointment_id, *, lock=False):  # noqa: ANN001, ANN202
        events.append("lock" if lock else "read")
        return real_appointment(session, group_id, appointment_id, lock=lock)

    def lapse_spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        events.append("lapse")
        return real_lapse(*args, **kwargs)

    def end_spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        events.append("end")
        return real_end(*args, **kwargs)

    monkeypatch.setattr(FamilyCalendarStore, "_appointment", staticmethod(appointment_spy))
    monkeypatch.setattr(family_asks, "lapse_due", lapse_spy)
    monkeypatch.setattr(family_asks, "_end", end_spy)

    sub = B if sub_key == "asked" else OWNER
    response = _act(client, group_id, ask["ask_id"], action, sub)
    assert response.status_code in (200, 204), response.text
    assert events[0] == "lock", events
    assert events.index("lock") < events.index("lapse") < events.index("end"), events


def test_answering_an_ask_whose_appointment_was_deleted_is_409(
    client: TestClient,  # noqa: F811
) -> None:
    """With the appointment gone there is nothing to lock; its asks were withdrawn with it, so
    answering is the same 409 as before (never a 404 or a 500)."""
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    appointment_id = occurrence.split("@")[0]
    deleted = client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=_headers(OWNER)
    )
    assert deleted.status_code in (200, 204), deleted.text
    for action, sub in (("accept", B), ("decline", B), ("withdraw", OWNER)):
        response = _act(client, group_id, ask["ask_id"], action, sub)
        assert response.status_code == 409, (action, response.text)


def _repeating(client: TestClient, group_id: str, first: date) -> str:  # noqa: F811
    return _appointment(
        client,
        group_id,
        first,
        repeat="weekly",
        repeat_until=(first + timedelta(days=21)).isoformat(),
    )


def test_editing_a_repeating_appointment_withdraws_only_asks_on_days_it_no_longer_has(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids = _family(client)
    first = _today() + timedelta(days=3)
    appointment_id = _repeating(client, group_id, first)
    week_one = _open_ask(client, group_id, _occurrence(appointment_id, first), ids[B])
    week_three = _open_ask(
        client, group_id, _occurrence(appointment_id, first + timedelta(days=14)), ids[C]
    )
    # The series now stops after the second week.
    changed = client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json={
            "title": "Physio",
            "kind": "therapy",
            "date": first.isoformat(),
            "start": "09:30",
            "end": "23:00",
            "repeat": "weekly",
            "repeat_until": (first + timedelta(days=7)).isoformat(),
        },
        headers=_headers(OWNER),
    )
    assert changed.status_code == 200, changed.text
    assert _state(repo, week_one["ask_id"]) == "open"
    assert _state(repo, week_three["ask_id"]) == "withdrawn"
    assert _kinds(client, C) == ["ask_received", "ask_withdrawn"]
    assert _kinds(client, B) == ["ask_received"]
    assert [a["ask_id"] for a in _open_asks(client, group_id)] == [week_one["ask_id"]]


def test_deleting_a_repeating_appointment_withdraws_every_open_ask_on_it(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids = _family(client)
    first = _today() + timedelta(days=3)
    appointment_id = _repeating(client, group_id, first)
    asks = [
        _open_ask(client, group_id, _occurrence(appointment_id, first), ids[B]),
        _open_ask(client, group_id, _occurrence(appointment_id, first + timedelta(days=7)), ids[C]),
    ]
    client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=_headers(OWNER)
    )
    assert [_state(repo, a["ask_id"]) for a in asks] == ["withdrawn", "withdrawn"]
    assert _kinds(client, B) == ["ask_received", "ask_withdrawn"]
    assert _kinds(client, C) == ["ask_received", "ask_withdrawn"]


# ── Notifications ─────────────────────────────────────────────────────────────


def test_notifications_page_newest_first_and_count_every_unread_one(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids = _family(client)
    appointment_id = _repeating(client, group_id, _today() + timedelta(days=3))
    first = _today() + timedelta(days=3)
    for week in range(4):
        _open_ask(
            client, group_id, _occurrence(appointment_id, first + timedelta(days=7 * week)), ids[B]
        )
    seen: list[str] = []
    page = _inbox(client, B, limit=3)
    assert page["unread_count"] == 4
    seen += [item["notification_id"] for item in page["items"]]
    assert page["next_before"] == seen[-1]
    page = _inbox(client, B, limit=3, before=page["next_before"])
    seen += [item["notification_id"] for item in page["items"]]
    assert page["next_before"] is None and page["unread_count"] == 4
    assert len(seen) == len(set(seen)) == 4
    dates = [item["on_date"] for item in _inbox(client, B)["items"]]
    assert dates == sorted(dates, reverse=True)  # asked one after another, newest first

    for params in ({"limit": 0}, {"limit": 51}):
        response = client.get("/v1/me/notifications", params=params, headers=_headers(B))
        assert response.status_code == 422


def test_a_foreign_or_unknown_page_marker_is_refused(client: TestClient) -> None:  # noqa: F811
    group_id, ids, occurrence = _setup(client)
    ask = _open_ask(client, group_id, occurrence, ids[B])
    _act(client, group_id, ask["ask_id"], "decline", B)
    owners = _inbox(client, OWNER)["items"][0]["notification_id"]
    for before in (owners, "ntf_nothing"):
        response = client.get(
            "/v1/me/notifications", params={"before": before}, headers=_headers(B)
        )
        assert response.status_code == 422


def test_marking_read_touches_only_the_callers_own_notifications(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids = _family(client)
    first = _today() + timedelta(days=3)
    appointment_id = _repeating(client, group_id, first)
    for week in range(2):
        day = first + timedelta(days=7 * week)
        ask = _open_ask(client, group_id, _occurrence(appointment_id, day), ids[B])
    _act(client, group_id, ask["ask_id"], "decline", B)  # one for Wei Ling
    owners = _inbox(client, OWNER)["items"][0]["notification_id"]
    [newest, oldest] = [i["notification_id"] for i in _inbox(client, B)["items"]]

    read = client.post(
        "/v1/me/notifications/read",
        json={"notification_ids": [newest, owners, "ntf_nothing"]},
        headers=_headers(B),
    )
    assert read.status_code == 204
    page = _inbox(client, B)
    assert page["unread_count"] == 1
    assert [i["read"] for i in page["items"]] == [True, False]
    # Wei Ling's was not Jun's to mark.
    assert _inbox(client, OWNER)["unread_count"] == 1

    assert (
        client.post(
            "/v1/me/notifications/read", json={"all": True}, headers=_headers(B)
        ).status_code
        == 204
    )
    assert _inbox(client, B)["unread_count"] == 0
    assert all(i["read"] for i in _inbox(client, B)["items"])
    assert _inbox(client, OWNER)["unread_count"] == 1
    assert oldest in [i["notification_id"] for i in _inbox(client, B)["items"]]

    for body in ({}, {"notification_ids": []}, {"notification_ids": [newest], "all": True}):
        response = client.post("/v1/me/notifications/read", json=body, headers=_headers(B))
        assert response.status_code == 422, body
    too_many = {"notification_ids": [f"ntf_{n}" for n in range(101)]}
    assert (
        client.post("/v1/me/notifications/read", json=too_many, headers=_headers(B)).status_code
        == 422
    )


def test_the_bell_covers_every_group_labelled_by_its_senior_and_no_one_else(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    _open_ask(client, group_id, occurrence, ids[B])
    # Jun has a second family, whose senior is not linked yet.
    other = client.post(
        "/v1/groups", json={"senior_name": "Mr Ong", "relationship": "Son"}, headers=_headers(B)
    ).json()["group_id"]
    _onboard(client, "family-e", "family", "Ah Boon")
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, other, sub=B), "relationship": "Cousin"},
        headers=_headers("family-e"),
    )
    pending = next(
        m
        for m in client.get(f"/v1/groups/{other}", headers=_headers(B)).json()["members"]
        if m["status"] == "pending"
    )
    client.post(f"/v1/groups/{other}/members/{pending['member_id']}/approve", headers=_headers(B))
    me_there = next(
        m["member_id"]
        for m in client.get(f"/v1/groups/{other}", headers=_headers(B)).json()["members"]
        if m["is_me"]
    )
    day = _today() + timedelta(days=5)
    appointment = client.post(
        f"/v1/groups/{other}/appointments",
        json={
            "title": "Haircut",
            "kind": "errand",
            "date": day.isoformat(),
            "start": "10:00",
            "end": "11:00",
        },
        headers=_headers(B),
    ).json()["appointment_id"]
    asked = client.post(
        f"/v1/groups/{other}/asks",
        json={"occurrence_id": _occurrence(appointment, day), "asked_member_id": me_there},
        headers=_headers("family-e"),
    )
    assert asked.status_code == 201, asked.text

    labels = {(i["group_id"], i["group_label"]) for i in _inbox(client, B)["items"]}
    assert labels == {(group_id, "Mdm Tan"), (other, "Mr Ong")}
    assert _inbox(client, B)["unread_count"] == 2
    # Someone in no group, and the senior's account, are never notified.
    _onboard(client, "family-new", "family", "Nobody")
    assert _inbox(client, "family-new") == {"items": [], "unread_count": 0, "next_before": None}
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        recipients = set(session.scalars(select(NotificationRow.recipient_member_id)))
    assert recipients == {ids[B], me_there}


def test_notifications_are_read_in_a_fixed_number_of_queries(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id, ids = _family(client)
    first = _today() + timedelta(days=3)
    appointment_id = _repeating(client, group_id, first)

    def count(n: int) -> int:
        statements: list[str] = []

        def _seen(*args: object) -> None:
            statements.append(str(args[2]))

        event.listen(repo.engine, "before_cursor_execute", _seen)
        try:
            assert len(_inbox(client, B, limit=50)["items"]) == n
        finally:
            event.remove(repo.engine, "before_cursor_execute", _seen)
        return len(statements)

    _open_ask(client, group_id, _occurrence(appointment_id, first), ids[B])
    one = count(1)
    for week in range(1, 4):
        _open_ask(
            client, group_id, _occurrence(appointment_id, first + timedelta(days=7 * week)), ids[B]
        )
    assert count(4) == one


# ── Sign-in off (the offline demo) ────────────────────────────────────────────


def _demo_group(demo: TestClient) -> str:  # noqa: F811
    return demo.get("/v1/me").json()["groups"][0]["group_id"]


def _demo_member(demo: TestClient, group_id: str, sub: str) -> str:  # noqa: F811
    members = demo.get(f"/v1/groups/{group_id}", headers={"X-Demo-Sub": sub}).json()["members"]
    return next(m["member_id"] for m in members if m["is_me"])


def _counts(repo: SqlAlchemyRepository) -> tuple[int, int]:  # noqa: F811
    with repo.sessions() as session:
        return (
            session.scalar(select(func.count()).select_from(HelperAskRow)) or 0,
            session.scalar(select(func.count()).select_from(NotificationRow)) or 0,
        )


def test_the_demo_senior_gets_an_empty_bell_and_no_asks(demo: TestClient) -> None:  # noqa: F811
    senior = {"X-Demo-Sub": "demo-senior"}
    response = demo.get("/v1/me/notifications", headers=senior)
    assert response.status_code == 200
    assert response.json() == {"items": [], "unread_count": 0, "next_before": None}
    assert (
        demo.post("/v1/me/notifications/read", json={"all": True}, headers=senior).status_code
        == 204
    )
    group_id = _demo_group(demo)
    assert demo.get(f"/v1/groups/{group_id}/asks", headers=senior).status_code == 404


def test_a_demo_reset_clears_the_demo_groups_asks_and_notifications(
    demo: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = _demo_group(demo)
    assert _counts(repo) == (0, 0)
    # Nobody has taken the doctor's visit in the demo schedule.
    calendar = demo.get(f"/v1/groups/{group_id}/calendar").json()
    doctor = next(o for o in calendar["appointments"] if o["appointment_id"] == "demo-doctor")
    emily = _demo_member(demo, group_id, "demo-emily")
    asked = demo.post(
        f"/v1/groups/{group_id}/asks",
        json={"occurrence_id": doctor["occurrence_id"], "asked_member_id": emily},
    )
    assert asked.status_code == 201, asked.text
    bell = demo.get("/v1/me/notifications", headers={"X-Demo-Sub": "demo-emily"}).json()
    assert [i["kind"] for i in bell["items"]] == ["ask_received"]
    assert bell["items"][0]["group_label"] == "Mdm Lim"
    # A newcomer, removed by the reset, asked about another day.
    newcomer = {"X-Demo-Sub": "demo-family-2"}
    pin = demo.post(f"/v1/groups/{group_id}/join-pin").json()["pin"]
    demo.post("/v1/groups/join", json={"pin": pin, "relationship": "Son"}, headers=newcomer)
    pending = next(
        m for m in demo.get(f"/v1/groups/{group_id}").json()["members"] if m["status"] == "pending"
    )
    demo.post(f"/v1/groups/{group_id}/members/{pending['member_id']}/approve")
    eye = next(o for o in calendar["appointments"] if o["appointment_id"] == "demo-eye")
    by_newcomer = demo.post(
        f"/v1/groups/{group_id}/asks",
        json={"occurrence_id": eye["occurrence_id"], "asked_member_id": emily},
        headers=newcomer,
    )
    assert by_newcomer.status_code == 201, by_newcomer.text
    assert _counts(repo) == (2, 2)

    for _ in range(2):
        assert demo.post("/v1/demo/reset").status_code == 200
        assert _counts(repo) == (0, 0)
        assert demo.get(f"/v1/groups/{group_id}/asks").json() == {"asks": []}


def test_a_demo_reset_removes_asks_in_unlinked_groups_a_demo_account_created(
    demo: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = demo.post(
        "/v1/groups", json={"senior_name": "Mr Ong", "relationship": "Son"}
    ).json()["group_id"]
    john = {"X-Demo-Sub": "demo-john"}
    pin = demo.post(f"/v1/groups/{group_id}/join-pin").json()["pin"]
    demo.post("/v1/groups/join", json={"pin": pin, "relationship": "Brother"}, headers=john)
    pending = next(
        m for m in demo.get(f"/v1/groups/{group_id}").json()["members"] if m["status"] == "pending"
    )
    demo.post(f"/v1/groups/{group_id}/members/{pending['member_id']}/approve")
    day = _today() + timedelta(days=4)
    appointment = demo.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Haircut",
            "kind": "errand",
            "date": day.isoformat(),
            "start": "09:00",
            "end": "10:00",
        },
    ).json()["appointment_id"]
    ask = demo.post(
        f"/v1/groups/{group_id}/asks",
        json={
            "occurrence_id": _occurrence(appointment, day),
            "asked_member_id": pending["member_id"],
        },
    )
    assert ask.status_code == 201, ask.text
    demo.post(f"/v1/groups/{group_id}/asks/{ask.json()['ask_id']}/decline", headers=john)
    assert _counts(repo) == (1, 2)

    assert demo.post("/v1/demo/reset").status_code == 200
    assert _counts(repo) == (0, 0)


def test_a_demo_reset_removes_asks_involving_the_demo_family_in_groups_they_joined(
    demo: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    someone = {"X-Demo-Sub": "someone-else"}
    other = {"X-Demo-Sub": "someone-other"}
    group_id = demo.post(
        "/v1/groups", json={"senior_name": "Mdm Koh", "relationship": "Son"}, headers=someone
    ).json()["group_id"]
    for joiner in ({}, other):
        pin = demo.post(f"/v1/groups/{group_id}/join-pin", headers=someone).json()["pin"]
        demo.post("/v1/groups/join", json={"pin": pin, "relationship": "Friend"}, headers=joiner)
        pending = next(
            m
            for m in demo.get(f"/v1/groups/{group_id}", headers=someone).json()["members"]
            if m["status"] == "pending"
        )
        demo.post(f"/v1/groups/{group_id}/members/{pending['member_id']}/approve", headers=someone)
    sarah = _demo_member(demo, group_id, "demo-family")
    owner = _demo_member(demo, group_id, "someone-else")
    third = _demo_member(demo, group_id, "someone-other")
    day = _today() + timedelta(days=4)
    appointment = demo.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Market",
            "kind": "errand",
            "date": day.isoformat(),
            "start": "09:00",
            "end": "10:00",
            "repeat": "daily",
            "repeat_until": (day + timedelta(days=5)).isoformat(),
        },
        headers=someone,
    ).json()["appointment_id"]

    def ask(on: date, asked: str, headers: dict[str, str]) -> str:
        response = demo.post(
            f"/v1/groups/{group_id}/asks",
            json={"occurrence_id": _occurrence(appointment, on), "asked_member_id": asked},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return response.json()["ask_id"]

    asked_sarah = ask(day, sarah, someone)
    by_sarah = ask(day + timedelta(days=1), owner, {})
    ended_by_sarah = ask(day + timedelta(days=2), third, someone)
    demo.post(
        f"/v1/groups/{group_id}/helpers",
        json={"occurrence_id": _occurrence(appointment, day + timedelta(days=2))},
    )
    kept = ask(day + timedelta(days=3), third, someone)
    assert _counts(repo) == (4, 6)

    assert demo.post("/v1/demo/reset").status_code == 200
    with repo.sessions() as session:
        left = set(session.scalars(select(HelperAskRow.ask_id)))
        notified = set(session.scalars(select(NotificationRow.ask_id)))
    assert left == {kept} and notified == {kept}
    assert {asked_sarah, by_sarah, ended_by_sarah}.isdisjoint(left)
    bell = demo.get("/v1/me/notifications", headers=other).json()
    assert [i["ask_id"] for i in bell["items"]] == [kept]


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


def test_asks_import_nothing_from_the_decision_path_or_the_calendar() -> None:
    forbidden = ("policy", "agent", "learning", "review_", "family_calendar")
    for name in _imports(_SOURCE / "family_asks.py"):
        parts = name.split(".")
        leaf = parts[1] if parts[0] == "silverloop" and len(parts) > 1 else parts[0]
        assert not leaf.startswith(forbidden), name


def test_nothing_on_the_decision_path_imports_asks() -> None:
    for package in ("policy.py", "review_threshold.py", "learning.py", "agent"):
        target = _SOURCE / package
        files = [target] if target.is_file() else sorted(target.rglob("*.py"))
        assert files
        for path in files:
            assert not any("family_asks" in name for name in _imports(path)), path


# ── Unread notifications per group (`MyGroup.unread_count` in `GET /v1/me`) ──────


def _unread_by_group(client: TestClient, sub: str) -> dict[str, int]:  # noqa: F811
    response = client.get("/v1/me", headers=_headers(sub))
    assert response.status_code == 200, response.text
    return {group["group_id"]: group["unread_count"] for group in response.json()["groups"]}


def test_an_ask_counts_as_unread_only_in_the_asked_members_group_until_the_bell_is_read(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, ids, occurrence = _setup(client)
    # Jun is also in a second family group, for another senior.
    _onboard(client, "senior-2", "senior", "Mr Lee")
    pin = client.post("/v1/me/link-pin", headers=_headers("senior-2")).json()["pin"]
    other = client.post(
        "/v1/groups", json={"senior_pin": pin, "relationship": "Son"}, headers=_headers(B)
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["group_id"]
    assert _unread_by_group(client, B) == {group_id: 0, other_id: 0}

    _open_ask(client, group_id, occurrence, ids[B])

    assert _unread_by_group(client, B) == {group_id: 1, other_id: 0}
    # Nobody else's count moves: the asker is not told of their own ask, Kai is not told at all.
    assert _unread_by_group(client, OWNER) == {group_id: 0}
    assert _unread_by_group(client, C) == {group_id: 0}

    # Opening the bell marks everything read, and the group's count follows.
    read = client.post("/v1/me/notifications/read", json={"all": True}, headers=_headers(B))
    assert read.status_code in (200, 204), read.text
    assert _unread_by_group(client, B) == {group_id: 0, other_id: 0}


def test_a_pending_membership_has_no_unread_count(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    _onboard(client, C, "family", "Kai")
    joined = client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Nephew"},
        headers=_headers(C),
    )
    assert joined.status_code in (200, 201), joined.text
    assert joined.json()["unread_count"] == 0
    assert _unread_by_group(client, C) == {group_id: 0}
