"""The family calendar, and family members reading their senior's activity."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.db_models import AppointmentRow
from silverloop.family_calendar import occurrence_dates
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
    _onboard,
    client,  # noqa: F401 - pytest fixture
    repo,  # noqa: F401 - pytest fixture
)

# ── Repeats ───────────────────────────────────────────────────────────────────


def _row(start: date, repeat: str, until: date | None = None) -> AppointmentRow:
    return AppointmentRow(start_date=start, repeat=repeat, repeat_until=until)


def test_a_one_off_appointment_has_one_day() -> None:
    row = _row(date(2026, 10, 20), "none")
    assert list(occurrence_dates(row, date(2026, 10, 1), date(2026, 10, 31))) == [
        date(2026, 10, 20)
    ]
    assert list(occurrence_dates(row, date(2026, 10, 21), date(2026, 10, 31))) == []


def test_weekly_repeats_start_from_the_first_day_in_range() -> None:
    row = _row(date(2026, 10, 1), "weekly", until=date(2026, 10, 29))
    days = list(occurrence_dates(row, date(2026, 10, 10), date(2026, 12, 31)))
    assert days == [date(2026, 10, 15), date(2026, 10, 22), date(2026, 10, 29)]


def test_daily_repeats_stop_at_the_range_end() -> None:
    row = _row(date(2026, 10, 1), "daily")
    days = list(occurrence_dates(row, date(2026, 9, 1), date(2026, 10, 3)))
    assert days == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]


def test_monthly_on_the_31st_skips_short_months() -> None:
    row = _row(date(2026, 1, 31), "monthly")
    days = list(occurrence_dates(row, date(2026, 1, 1), date(2026, 6, 30)))
    assert days == [date(2026, 1, 31), date(2026, 3, 31), date(2026, 5, 31)]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _senior_person(client: TestClient) -> str:  # noqa: F811
    return client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]


def _member_b(client: TestClient, group_id: str, *, approve: bool = True) -> None:  # noqa: F811
    _onboard(client, "family-b", "family", "Jun")
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers("family-b"),
    )
    if approve:
        group = client.get(f"/v1/groups/{group_id}", headers=_headers("family-a")).json()
        pending = next(m for m in group["members"] if m["status"] == "pending")
        client.post(
            f"/v1/groups/{group_id}/members/{pending['member_id']}/approve",
            headers=_headers("family-a"),
        )


def _weekly(client: TestClient, group_id: str, start: date) -> str:  # noqa: F811
    response = client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "Physio",
            "kind": "therapy",
            "date": start.isoformat(),
            "start": "14:00",
            "end": "15:00",
            "repeat": "weekly",
            "repeat_until": (start + timedelta(days=21)).isoformat(),
        },
        headers=_headers("family-a"),
    )
    assert response.status_code == 201, response.text
    return response.json()["appointment_id"]


def _calendar(client: TestClient, person_id: str, sub: str, **params: str):  # noqa: F811
    return client.get(f"/v1/people/{person_id}/calendar", params=params, headers=_headers(sub))


# ── Reading the senior's activity ─────────────────────────────────────────────


def test_an_active_member_reads_their_seniors_activity(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    assert (
        client.get(f"/v1/people/{person_id}/state", headers=_headers("family-a")).status_code == 200
    )
    metrics = client.get(f"/v1/people/{person_id}/metrics", headers=_headers("family-a"))
    assert metrics.status_code == 200 and metrics.json()

    # A pending member and an outsider cannot, and are told the person does not exist.
    _member_b(client, group_id, approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("family-b", "outsider"):
        assert client.get(f"/v1/people/{person_id}/state", headers=_headers(sub)).status_code == 404
        assert _calendar(client, person_id, sub).status_code == 404
    # A senior still reads only themselves; a coordinator still cannot read this route.
    _onboard(client, "senior-2", "senior", "Mr Goh")
    assert (
        client.get(f"/v1/people/{person_id}/state", headers=_headers("senior-2")).status_code == 404
    )
    coordinator = _headers("coordinator-1", role="coordinator")
    assert client.get(f"/v1/people/{person_id}/state", headers=coordinator).status_code == 403


# ── The calendar ──────────────────────────────────────────────────────────────


def test_a_weekly_appointment_shows_each_week_to_the_family_and_the_senior(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    start = date(2026, 11, 2)
    appointment_id = _weekly(client, group_id, start)

    for sub in ("family-a", "senior-1"):
        response = _calendar(client, person_id, sub, from_date="2026-11-01", to_date="2026-12-31")
        assert response.status_code == 200, response.text
        days = [o["occurrence_id"] for o in response.json()["appointments"]]
        assert days == [
            f"{appointment_id}@{(start + timedelta(days=7 * week)).isoformat()}"
            for week in range(4)
        ]
    me = [m for m in _calendar(client, person_id, "family-a").json()["members"] if m["is_me"]]
    assert [m["display_name"] for m in me] == ["Wei Ling"]


def test_helping_answering_and_stepping_back_follow_the_browser_rules(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    appointment_id = _weekly(client, group_id, date(2026, 11, 2))
    day = f"{appointment_id}@2026-11-09"
    owner = _headers("family-a")

    def state():
        body = _calendar(
            client, person_id, "family-a", from_date="2026-11-01", to_date="2026-11-30"
        ).json()
        answers = {
            (a["occurrence_id"], a["status"]) for a in body["availability"] if a["occurrence_id"]
        }
        helpers = {a["occurrence_id"] for a in body["assignments"]}
        return answers, helpers

    assert (
        client.post(
            f"/v1/groups/{group_id}/helpers", json={"occurrence_id": day}, headers=owner
        ).status_code
        == 204
    )
    assert state() == ({(day, "available")}, {day})

    # Stepping back keeps the answer.
    client.post(
        f"/v1/groups/{group_id}/helpers/step-back", json={"occurrence_id": day}, headers=owner
    )
    assert state() == ({(day, "available")}, set())

    # Not available replaces the answer and takes them off.
    client.post(f"/v1/groups/{group_id}/helpers", json={"occurrence_id": day}, headers=owner)
    client.post(
        f"/v1/groups/{group_id}/answers",
        json={"occurrence_id": day, "status": "unavailable"},
        headers=owner,
    )
    assert state() == ({(day, "unavailable")}, set())

    # A day the appointment does not have is not an occurrence.
    missing = client.post(
        f"/v1/groups/{group_id}/helpers",
        json={"occurrence_id": f"{appointment_id}@2026-11-10"},
        headers=owner,
    )
    assert missing.status_code == 404


def test_members_change_only_their_own_availability(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    _member_b(client, group_id)
    window = {"date": "2026-11-05", "start": "09:00", "end": "12:00", "status": "available"}
    created = client.post(
        f"/v1/groups/{group_id}/availability", json=window, headers=_headers("family-a")
    )
    assert created.status_code == 201
    entry_id = created.json()["entry_id"]
    path = f"/v1/groups/{group_id}/availability/{entry_id}/delete"
    assert client.post(path, headers=_headers("family-b")).status_code == 404
    assert client.post(path, headers=_headers("family-a")).status_code == 204

    backwards = {**window, "start": "12:00", "end": "09:00"}
    response = client.post(
        f"/v1/groups/{group_id}/availability", json=backwards, headers=_headers("family-a")
    )
    assert response.status_code == 422


def test_deleting_an_appointment_removes_its_answers_and_helpers(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    appointment_id = _weekly(client, group_id, date(2026, 11, 2))
    owner = _headers("family-a")
    client.post(
        f"/v1/groups/{group_id}/helpers",
        json={"occurrence_id": f"{appointment_id}@2026-11-02"},
        headers=owner,
    )
    deleted = client.post(
        f"/v1/groups/{group_id}/appointments/{appointment_id}/delete", headers=owner
    )
    assert deleted.status_code == 204
    body = _calendar(
        client, person_id, "family-a", from_date="2026-11-01", to_date="2026-11-30"
    ).json()
    assert body["appointments"] == [] and body["availability"] == [] and body["assignments"] == []


def test_outsiders_cannot_write_to_a_group(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    _onboard(client, "outsider", "family", "Stranger")
    response = client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "X",
            "kind": "errand",
            "date": "2026-11-02",
            "start": "09:00",
            "end": "10:00",
        },
        headers=_headers("outsider"),
    )
    assert response.status_code == 404


def test_an_appointment_cannot_end_before_it_starts(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    response = client.post(
        f"/v1/groups/{group_id}/appointments",
        json={
            "title": "X",
            "kind": "errand",
            "date": "2026-11-02",
            "start": "10:00",
            "end": "09:00",
        },
        headers=_headers("family-a"),
    )
    assert response.status_code == 422


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


def test_the_demo_family_and_schedule_start_alike_after_a_reset(demo: TestClient) -> None:
    body = demo.get("/v1/people/mdm-lim/calendar").json()
    assert [m["display_name"] for m in body["members"]] == ["Sarah", "John", "Emily"]
    assert [m["is_me"] for m in body["members"]] == [True, False, False]
    assert len(body["appointments"]) == 8
    assert len(body["assignments"]) == 4

    john = demo.get("/v1/people/mdm-lim/calendar", headers={"X-Demo-Sub": "demo-john"}).json()
    assert [m["is_me"] for m in john["members"]] == [False, True, False]

    doctor = next(o for o in body["appointments"] if o["title"].startswith("Doctor"))
    demo.post(
        f"/v1/groups/{body['group_id']}/helpers", json={"occurrence_id": doctor["occurrence_id"]}
    )
    assert len(demo.get("/v1/people/mdm-lim/calendar").json()["assignments"]) == 5

    assert demo.post("/v1/demo/reset").status_code == 200
    again = demo.get("/v1/people/mdm-lim/calendar").json()
    assert len(again["assignments"]) == 4
    assert [m["display_name"] for m in again["members"]] == ["Sarah", "John", "Emily"]
