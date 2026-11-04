"""Appointment notes: per day of an appointment, for the family group only."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.config import Settings
from silverloop.db_models import AppointmentNoteRow, AuditEventRow, FamilyActivityRow
from silverloop.family_groups import DEMO_JOHN_SUB
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_family_activity import (
    _appointment_body,
    _entries,
    _new_appointment,
    repo,  # noqa: F401 - pytest fixture: the in-memory database with foreign keys enforced
)
from tests.test_family_calendar import _calendar, _member_b, _senior_person, _weekly
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _onboard,
    client,  # noqa: F401 - pytest fixture
)

OWNER = "family-a"
DAY = "2026-11-12"  # `_appointment_body`'s one-off day
SECRET = "Bring the blue folder, locker code 4417"
# What must never leak. The whole phrase, not just "4417": random hex ids (`act_cf441719…`) can
# contain those four digits by chance, but never a phrase with spaces and letters like this.
LEAK = "locker code 4417"


def _notes_url(group_id: str, appointment_id: str) -> str:
    return f"/v1/groups/{group_id}/appointments/{appointment_id}/notes"


def _add(
    client: TestClient,  # noqa: F811
    group_id: str,
    appointment_id: str,
    text: str = "Bring her IC",
    day: str = DAY,
    sub: str = OWNER,
):
    return client.post(
        _notes_url(group_id, appointment_id),
        json={"date": day, "text": text},
        headers=_headers(sub),
    )


def _list(
    client: TestClient,  # noqa: F811
    group_id: str,
    appointment_id: str,
    day: str = DAY,
    sub: str = OWNER,
):
    return client.get(
        _notes_url(group_id, appointment_id), params={"date": day}, headers=_headers(sub)
    )


def _delete(client: TestClient, group_id: str, note_id: str, sub: str = OWNER):  # noqa: F811
    return client.post(f"/v1/groups/{group_id}/notes/{note_id}/delete", headers=_headers(sub))


def _setup(client: TestClient) -> tuple[str, str]:  # noqa: F811
    group_id = _group_with_owner(client)
    return group_id, _new_appointment(client, group_id)


def _second_group(client: TestClient) -> str:  # noqa: F811
    _onboard(client, "senior-2", "senior", "Mr Lee")
    _onboard(client, "family-x", "family", "Xin")
    pin = client.post("/v1/me/link-pin", headers=_headers("senior-2")).json()["pin"]
    response = client.post(
        "/v1/groups",
        json={"senior_pin": pin, "relationship": "Son"},
        headers=_headers("family-x"),
    )
    assert response.status_code == 201, response.text
    return response.json()["group_id"]


# ── Adding and reading ────────────────────────────────────────────────────────


def test_adding_a_note_returns_it_and_records_note_added_without_the_text(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    response = _add(client, group_id, appointment_id, SECRET)
    assert response.status_code == 201, response.text
    note = response.json()
    assert note["text"] == SECRET
    assert note["appointment_id"] == appointment_id
    assert note["occurrence_id"] == f"{appointment_id}@{DAY}"
    assert note["author_name"] == "Wei Ling" and note["is_mine"] is True
    assert note["note_id"].startswith("note_") and note["member_id"].startswith("mem_")

    latest = _entries(client, group_id)[0]
    assert latest["kind"] == "note_added"
    assert latest["actor_name"] == "Wei Ling" and latest["is_me"] is True
    assert latest["appointment_title"] == "Eye check-up" and latest["appointment_kind"] == "medical"
    assert latest["on_date"] == DAY
    assert latest["occurrence_id"] == f"{appointment_id}@{DAY}"
    assert latest["note"] is None and LEAK not in str(_entries(client, group_id))

    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        row = session.scalar(
            select(FamilyActivityRow).where(FamilyActivityRow.kind == "note_added")
        )
        assert row is not None and row.note is None and row.check_in_kind is None
        assert LEAK not in str(vars(row))
        for event in session.scalars(select(AuditEventRow)):
            assert LEAK not in str(vars(event))


def test_note_text_never_reaches_the_logs(
    client: TestClient,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    group_id, appointment_id = _setup(client)
    with caplog.at_level(logging.DEBUG):
        assert _add(client, group_id, appointment_id, SECRET).status_code == 201
        assert _list(client, group_id, appointment_id).status_code == 200
    assert LEAK not in caplog.text


def test_notes_are_trimmed_and_listed_oldest_first_with_is_mine_per_viewer(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    _member_b(client, group_id)
    first = _add(client, group_id, appointment_id, "  first  ", sub=OWNER).json()
    second = _add(client, group_id, appointment_id, "second", sub="family-b").json()
    third = _add(client, group_id, appointment_id, "third", sub=OWNER).json()
    assert first["text"] == "first"

    as_owner = _list(client, group_id, appointment_id, sub=OWNER).json()
    assert [n["note_id"] for n in as_owner] == [
        first["note_id"],
        second["note_id"],
        third["note_id"],
    ]
    assert [n["is_mine"] for n in as_owner] == [True, False, True]
    assert [n["author_name"] for n in as_owner] == ["Wei Ling", "Jun", "Wei Ling"]

    as_jun = _list(client, group_id, appointment_id, sub="family-b").json()
    assert [n["is_mine"] for n in as_jun] == [False, True, False]


def test_notes_belong_to_one_day_of_a_repeating_appointment(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    appointment_id = _weekly(client, group_id, date(2026, 11, 2))
    assert _add(client, group_id, appointment_id, "week one", day="2026-11-02").status_code == 201
    assert _add(client, group_id, appointment_id, "week two", day="2026-11-09").status_code == 201
    [only] = _list(client, group_id, appointment_id, day="2026-11-09").json()
    assert only["text"] == "week two" and only["occurrence_id"] == f"{appointment_id}@2026-11-09"
    assert _list(client, group_id, appointment_id, day="2026-11-16").json() == []
    # Not a day of the series.
    assert _list(client, group_id, appointment_id, day="2026-11-03").status_code == 404


def test_a_day_holds_at_most_one_hundred_notes_and_the_101st_is_409(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    first = _add(client, group_id, appointment_id, "n0").json()
    with client.app.state.repository.sessions.begin() as session:  # type: ignore[attr-defined]
        template = session.get(AppointmentNoteRow, first["note_id"])
        assert template is not None
        for index in range(1, 100):
            session.add(
                AppointmentNoteRow(
                    note_id=f"note_bulk{index:04d}",
                    group_id=template.group_id,
                    appointment_id=template.appointment_id,
                    on_date=template.on_date,
                    member_id=template.member_id,
                    text=f"n{index}",
                    created_at=template.created_at + timedelta(seconds=index),
                )
            )
    notes = _list(client, group_id, appointment_id).json()
    assert len(notes) == 100
    assert notes[0]["text"] == "n0" and notes[-1]["text"] == "n99"

    feed_before = len(_entries(client, group_id))
    full = _add(client, group_id, appointment_id, "one too many")
    assert full.status_code == 409
    assert full.json()["detail"] == "This day already has the most notes it can hold"
    assert len(_entries(client, group_id)) == feed_before
    assert len(_list(client, group_id, appointment_id).json()) == 100
    # Another day of the same appointment is not affected, and removing one frees a place.
    assert _delete(client, group_id, first["note_id"]).status_code == 204
    assert _add(client, group_id, appointment_id, "fits now").status_code == 201


# ── Validation ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_a_blank_note_is_refused(client: TestClient, text: str) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    before = len(_entries(client, group_id))
    assert _add(client, group_id, appointment_id, text).status_code == 422
    assert _list(client, group_id, appointment_id).json() == []
    assert len(_entries(client, group_id)) == before


def test_a_note_is_at_most_500_characters_after_trimming(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    assert _add(client, group_id, appointment_id, "x" * 501).status_code == 422
    assert _add(client, group_id, appointment_id, f"  {'x' * 500}  ").status_code == 201


def test_the_date_is_required_and_must_be_a_date(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    owner = _headers(OWNER)
    assert client.get(_notes_url(group_id, appointment_id), headers=owner).status_code == 422
    assert _list(client, group_id, appointment_id, day="tomorrow").status_code == 422
    response = client.post(_notes_url(group_id, appointment_id), json={"text": "hi"}, headers=owner)
    assert response.status_code == 422


def test_a_day_that_is_not_an_occurrence_is_404_and_writes_nothing(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    before = len(_entries(client, group_id))
    assert _add(client, group_id, appointment_id, day="2026-11-13").status_code == 404
    assert _list(client, group_id, appointment_id, day="2026-11-13").status_code == 404
    assert len(_entries(client, group_id)) == before


def test_an_unknown_appointment_or_one_in_another_group_is_404(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    assert _add(client, group_id, "appt_unknown").status_code == 404
    assert _list(client, group_id, "appt_unknown").status_code == 404
    # A second family with its own group: the first family's appointment is not theirs.
    other = _second_group(client)
    assert _add(client, other, appointment_id, sub="family-x").status_code == 404
    assert _list(client, other, appointment_id, sub="family-x").status_code == 404


# ── Deleting ──────────────────────────────────────────────────────────────────


def test_an_author_deletes_their_own_note_and_the_feed_entry_stays(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    note = _add(client, group_id, appointment_id).json()
    response = _delete(client, group_id, note["note_id"])
    assert response.status_code == 204 and response.content == b""
    assert _list(client, group_id, appointment_id).json() == []
    assert [e["kind"] for e in _entries(client, group_id)].count("note_added") == 1
    assert _delete(client, group_id, note["note_id"]).status_code == 404


def test_another_members_note_is_403_and_stays(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    _member_b(client, group_id)
    note = _add(client, group_id, appointment_id, sub="family-b").json()
    response = _delete(client, group_id, note["note_id"], sub=OWNER)
    assert response.status_code == 403
    assert response.json()["detail"] == "You can only remove your own notes"
    assert len(_list(client, group_id, appointment_id).json()) == 1


def test_an_unknown_note_or_one_in_another_group_is_404(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    note = _add(client, group_id, appointment_id).json()
    assert _delete(client, group_id, "note_nope").status_code == 404

    other = _second_group(client)
    # The other group's member, naming either group; and the owner naming a group they are not in.
    assert _delete(client, other, note["note_id"], sub="family-x").status_code == 404
    assert _delete(client, group_id, note["note_id"], sub="family-x").status_code == 404
    assert _delete(client, other, note["note_id"], sub=OWNER).status_code == 404
    assert len(_list(client, group_id, appointment_id).json()) == 1


def test_deleting_the_appointment_removes_its_notes_with_foreign_keys_enforced(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    other_id = _new_appointment(client, group_id, title="Dentist")
    _add(client, group_id, appointment_id)
    kept = _add(client, group_id, other_id).json()
    response = client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=_headers(OWNER)
    )
    assert response.status_code == 204, response.text
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        left = list(session.scalars(select(AppointmentNoteRow.note_id)))
    assert left == [kept["note_id"]]
    assert _entries(client, group_id)[0]["kind"] == "appointment_removed"


def test_notes_on_a_day_the_appointment_no_longer_has_are_deleted(
    client: TestClient,  # noqa: F811
) -> None:
    group_id, appointment_id = _setup(client)
    _add(client, group_id, appointment_id, "on the old day")
    feed_before = len(_entries(client, group_id))
    moved = client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json=_appointment_body(date="2026-11-19"),
        headers=_headers(OWNER),
    )
    assert moved.status_code == 200, moved.text
    assert _list(client, group_id, appointment_id, day=DAY).status_code == 404
    assert _list(client, group_id, appointment_id, day="2026-11-19").json() == []
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        assert list(session.scalars(select(AppointmentNoteRow.note_id))) == []
    # Only the change itself was recorded; the earlier note_added entry stays, with no text.
    kinds = [e["kind"] for e in _entries(client, group_id)]
    assert len(kinds) == feed_before + 1 and kinds.count("note_added") == 1
    # The note does not come back if the appointment returns to that day.
    client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json=_appointment_body(),
        headers=_headers(OWNER),
    )
    assert _list(client, group_id, appointment_id).json() == []


def test_changing_a_repeat_deletes_only_the_notes_of_days_it_dropped(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    appointment_id = _weekly(client, group_id, date(2026, 11, 2))  # 2, 9, 16, 23 November
    for day in ("2026-11-02", "2026-11-09", "2026-11-23"):
        assert _add(client, group_id, appointment_id, f"on {day}", day=day).status_code == 201
    changed = client.put(
        f"/v1/groups/{group_id}/appointments/{appointment_id}",
        json={
            "title": "Physio",
            "kind": "therapy",
            "date": "2026-11-02",
            "start": "14:00",
            "end": "15:00",
            "repeat": "weekly",
            "repeat_until": "2026-11-12",
        },
        headers=_headers(OWNER),
    )
    assert changed.status_code == 200, changed.text
    with client.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
        left = sorted(session.scalars(select(AppointmentNoteRow.text)))
    assert left == ["on 2026-11-02", "on 2026-11-09"]
    # A day the new repeat still has keeps its note.
    assert [
        n["text"] for n in _list(client, group_id, appointment_id, day="2026-11-09").json()
    ] == ["on 2026-11-09"]


# ── Who may use them ──────────────────────────────────────────────────────────


def test_only_active_members_use_notes(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    note = _add(client, group_id, appointment_id).json()
    _member_b(client, group_id, approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("family-b", "outsider"):  # pending, and not a member
        assert _add(client, group_id, appointment_id, sub=sub).status_code == 404
        assert _list(client, group_id, appointment_id, sub=sub).status_code == 404
        assert _delete(client, group_id, note["note_id"], sub=sub).status_code == 404
    assert _add(client, "grp_unknown", appointment_id).status_code == 404
    assert _list(client, "grp_unknown", appointment_id).status_code == 404
    assert _delete(client, "grp_unknown", note["note_id"]).status_code == 404
    assert len(_list(client, group_id, appointment_id).json()) == 1


def test_the_senior_with_sign_in_on_is_refused(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    note = _add(client, group_id, appointment_id).json()
    assert _add(client, group_id, appointment_id, sub="senior-1").status_code == 403
    assert _list(client, group_id, appointment_id, sub="senior-1").status_code == 403
    assert _delete(client, group_id, note["note_id"], sub="senior-1").status_code == 403


def test_the_calendar_the_senior_reads_has_no_note_data(client: TestClient) -> None:  # noqa: F811
    group_id, appointment_id = _setup(client)
    _add(client, group_id, appointment_id, SECRET)
    person_id = _senior_person(client)
    for sub in ("senior-1", OWNER):
        response = _calendar(client, person_id, sub, from_date="2026-11-01", to_date="2026-11-30")
        assert response.status_code == 200
        assert LEAK not in response.text and "note_id" not in response.text
        body = response.json()
        [appointment] = body["appointments"]
        # The appointment's own details field is untouched by notes.
        assert appointment["notes"] is None
        assert set(body) == {
            "person_id",
            "senior_name",
            "group_id",
            "from_date",
            "to_date",
            "members",
            "appointments",
            "availability",
            "assignments",
        }


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


def _demo_doctor(demo: TestClient) -> tuple[str, str, str]:
    group = demo.get("/v1/me").json()["groups"][0]
    calendar = demo.get(f"/v1/people/{group['person_id']}/calendar").json()
    doctor = next(a for a in calendar["appointments"] if a["appointment_id"] == "demo-doctor")
    return group["group_id"], doctor["appointment_id"], doctor["date"]


def test_the_demo_senior_is_not_a_member_so_notes_are_404(demo: TestClient) -> None:
    group_id, appointment_id, day = _demo_doctor(demo)
    senior = {"X-Demo-Sub": "demo-senior"}
    url = _notes_url(group_id, appointment_id)
    assert demo.get(url, params={"date": day}, headers=senior).status_code == 404
    assert demo.post(url, json={"date": day, "text": "hi"}, headers=senior).status_code == 404


def test_the_demo_seeds_one_note_and_its_feed_entry_and_a_reset_restores_them(
    demo: TestClient,
) -> None:
    group_id, appointment_id, day = _demo_doctor(demo)
    url = _notes_url(group_id, appointment_id)

    def notes(headers: dict[str, str] | None = None) -> list[dict]:
        return demo.get(url, params={"date": day}, headers=headers).json()

    [note] = notes()
    assert note["text"] == "I'll bring her NRIC and health booklet, they're in the blue folder."
    assert note["author_name"] == "Sarah" and note["is_mine"] is True
    feed = demo.get(f"/v1/groups/{group_id}/activity", params={"limit": 50}).json()["entries"]
    [added] = [e for e in feed if e["kind"] == "note_added"]
    assert added["origin"] == "demo_seed" and added["note"] is None
    assert added["actor_name"] == "Sarah" and added["occurrence_id"] == f"{appointment_id}@{day}"

    # Another demo member sees it as someone else's and cannot remove it.
    john = {"X-Demo-Sub": DEMO_JOHN_SUB}
    [seen] = notes(john)
    assert seen["is_mine"] is False
    removed = demo.post(f"/v1/groups/{group_id}/notes/{note['note_id']}/delete", headers=john)
    assert removed.status_code == 403

    # Live notes are cleared by a reset, every time, with foreign keys enforced.
    assert demo.post(url, json={"date": day, "text": "live note"}).status_code == 201
    assert len(notes()) == 2
    for _ in range(2):
        assert demo.post("/v1/demo/reset").status_code == 200
        [again] = notes()
        assert (
            again["text"] == "I'll bring her NRIC and health booklet, they're in the blue folder."
        )
        with demo.app.state.repository.sessions() as session:  # type: ignore[attr-defined]
            assert len(list(session.scalars(select(AppointmentNoteRow.note_id)))) == 1
