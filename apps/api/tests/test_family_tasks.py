"""Tasks: the senior's shared reminder list, kept by their family group and ticked done by day.

Foreign keys are enforced (the `repo` fixture from `test_family_activity`), so deleting a task with
its ticks and the demo reset's delete order are checked here as on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from silverloop.local_time import local_date
from tests.test_family_activity import repo  # noqa: F401 - pytest fixture (foreign keys on)
from tests.test_family_calendar import demo  # noqa: F401 - pytest fixture
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
    _onboard,
    client,  # noqa: F401 - pytest fixture
)

OWNER = "family-a"


def _today() -> date:
    return local_date(datetime.now(UTC))


def _senior_person(client: TestClient) -> str:  # noqa: F811
    return client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]


def _task(client: TestClient, group_id: str, **fields) -> dict:  # noqa: F811
    body = {
        "title": "Water the plants",
        "start_date": (_today() - timedelta(days=3)).isoformat(),
        "time": "09:00",
        "repeat": "daily",
    } | fields
    response = client.post(f"/v1/groups/{group_id}/tasks", json=body, headers=_headers(OWNER))
    assert response.status_code == 201, response.text
    return response.json()


def _group_list(client: TestClient, group_id: str, sub: str = OWNER) -> dict:  # noqa: F811
    response = client.get(f"/v1/groups/{group_id}/tasks", headers=_headers(sub))
    assert response.status_code == 200, response.text
    return response.json()


def _tick_group(client, group_id, task_id, day: date, done=True, sub=OWNER):  # noqa: F811
    return client.put(
        f"/v1/groups/{group_id}/tasks/{task_id}/days/{day.isoformat()}",
        json={"done": done},
        headers=_headers(sub),
    )


def _tick_person(client, person_id, task_id, day: date, done=True, sub="senior-1"):  # noqa: F811
    return client.put(
        f"/v1/people/{person_id}/tasks/{task_id}/days/{day.isoformat()}",
        json={"done": done},
        headers=_headers(sub),
    )


def _member(client: TestClient, group_id: str, sub: str, *, approve: bool) -> None:  # noqa: F811
    _onboard(client, sub, "family", sub.title())
    client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers(sub),
    )
    if approve:
        group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
        pending = next(m for m in group["members"] if m["status"] == "pending")
        client.post(
            f"/v1/groups/{group_id}/members/{pending['member_id']}/approve",
            headers=_headers(OWNER),
        )


# ── Adding, changing, deleting ────────────────────────────────────────────────


def test_a_family_member_adds_a_task_that_the_group_and_the_senior_both_read(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    task = _task(client, group_id, kind="medicine", notes="  With breakfast  ")
    assert task["kind"] == "medicine"
    assert task["notes"] == "With breakfast"
    assert task["added_by_name"] == "Wei Ling"

    group_view = _group_list(client, group_id)
    assert [t["task_id"] for t in group_view["tasks"]] == [task["task_id"]]
    assert group_view["group_id"] == group_id and group_view["person_id"] == person_id

    senior_view = client.get(f"/v1/people/{person_id}/tasks", headers=_headers("senior-1"))
    assert senior_view.status_code == 200
    assert [t["task_id"] for t in senior_view.json()["tasks"]] == [task["task_id"]]


def test_only_active_members_manage_tasks_the_senior_gets_403_and_others_404(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    task_id = _task(client, group_id)["task_id"]
    body = {"title": "X", "start_date": _today().isoformat(), "time": "10:00"}

    senior = _headers("senior-1")
    assert client.post(f"/v1/groups/{group_id}/tasks", json=body, headers=senior).status_code == 403
    assert (
        client.put(f"/v1/groups/{group_id}/tasks/{task_id}", json=body, headers=senior).status_code
        == 403
    )
    assert (
        client.post(f"/v1/groups/{group_id}/tasks/{task_id}/delete", headers=senior).status_code
        == 403
    )
    assert client.get(f"/v1/groups/{group_id}/tasks", headers=senior).status_code == 403

    _member(client, group_id, "pending-1", approve=False)
    _onboard(client, "outsider", "family", "Stranger")
    for sub in ("pending-1", "outsider"):
        headers = _headers(sub)
        assert client.get(f"/v1/groups/{group_id}/tasks", headers=headers).status_code == 404
        assert client.get(f"/v1/people/{person_id}/tasks", headers=headers).status_code == 404
        assert (
            client.post(f"/v1/groups/{group_id}/tasks", json=body, headers=headers).status_code
            == 404
        )
        assert _tick_group(client, group_id, task_id, _today(), sub=sub).status_code == 404
        assert _tick_person(client, person_id, task_id, _today(), sub=sub).status_code == 404

    # Another senior cannot read or tick this one's tasks.
    _onboard(client, "senior-2", "senior", "Mr Goh")
    assert (
        client.get(f"/v1/people/{person_id}/tasks", headers=_headers("senior-2")).status_code == 404
    )
    assert _tick_person(client, person_id, task_id, _today(), sub="senior-2").status_code == 404


def test_editing_keeps_the_ticks_and_deleting_removes_them(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    task_id = _task(client, group_id)["task_id"]
    yesterday = _today() - timedelta(days=1)
    assert _tick_group(client, group_id, task_id, yesterday).status_code == 204

    changed = client.put(
        f"/v1/groups/{group_id}/tasks/{task_id}",
        json={
            "title": "Water the orchids",
            "start_date": (_today() - timedelta(days=3)).isoformat(),
            "time": "08:30",
            "repeat": "daily",
        },
        headers=_headers(OWNER),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["title"] == "Water the orchids"
    assert [t["day"] for t in _group_list(client, group_id)["ticks"]] == [yesterday.isoformat()]

    # A one-off on another day: the old tick is kept but no longer one of its days, so not shown.
    client.put(
        f"/v1/groups/{group_id}/tasks/{task_id}",
        json={"title": "Once", "start_date": _today().isoformat(), "time": "08:30"},
        headers=_headers(OWNER),
    )
    assert _group_list(client, group_id)["ticks"] == []

    deleted = client.post(f"/v1/groups/{group_id}/tasks/{task_id}/delete", headers=_headers(OWNER))
    assert deleted.status_code == 204
    assert _group_list(client, group_id) | {"from_date": None, "to_date": None} == {
        "person_id": _senior_person(client),
        "group_id": group_id,
        "from_date": None,
        "to_date": None,
        "tasks": [],
        "ticks": [],
    }
    assert (
        client.post(
            f"/v1/groups/{group_id}/tasks/{task_id}/delete", headers=_headers(OWNER)
        ).status_code
        == 404
    )


def test_a_repeat_cannot_end_before_its_first_day(client: TestClient) -> None:  # noqa: F811
    group_id = _group_with_owner(client)
    response = client.post(
        f"/v1/groups/{group_id}/tasks",
        json={
            "title": "Walk",
            "start_date": "2026-11-10",
            "time": "07:00",
            "repeat": "weekly",
            "repeat_until": "2026-11-01",
        },
        headers=_headers(OWNER),
    )
    assert response.status_code == 422


# ── Ticking a day done ────────────────────────────────────────────────────────


def test_the_senior_ticks_today_only_and_the_family_also_past_days(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    person_id = _senior_person(client)
    task_id = _task(client, group_id)["task_id"]
    today, yesterday = _today(), _today() - timedelta(days=1)

    assert _tick_person(client, person_id, task_id, today).status_code == 204
    assert _tick_person(client, person_id, task_id, yesterday).status_code == 422
    assert _tick_group(client, group_id, task_id, yesterday).status_code == 204

    ticks = {t["day"]: t for t in _group_list(client, group_id)["ticks"]}
    assert ticks[today.isoformat()]["done_by_name"] == "Mdm Tan"
    assert ticks[yesterday.isoformat()]["done_by_name"] == "Wei Ling"

    # The senior un-ticks today; ticking twice or un-ticking twice changes nothing.
    assert _tick_person(client, person_id, task_id, today, done=False).status_code == 204
    assert _tick_person(client, person_id, task_id, today, done=False).status_code == 204
    assert _tick_group(client, group_id, task_id, yesterday).status_code == 204
    assert [t["day"] for t in _group_list(client, group_id)["ticks"]] == [yesterday.isoformat()]


def test_nobody_ticks_a_future_day_or_a_day_the_task_is_not_on(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    tomorrow = _today() + timedelta(days=1)
    daily = _task(client, group_id)["task_id"]
    assert _tick_group(client, group_id, daily, tomorrow).status_code == 422

    weekly = _task(
        client, group_id, start_date=(_today() - timedelta(days=7)).isoformat(), repeat="weekly"
    )["task_id"]
    assert _tick_group(client, group_id, weekly, _today()).status_code == 204
    assert _tick_group(client, group_id, weekly, _today() - timedelta(days=1)).status_code == 422
    assert _group_list(client, group_id)["ticks"][0]["task_id"] == weekly


# ── Before the senior is linked ───────────────────────────────────────────────


def test_a_group_with_no_senior_linked_keeps_tasks_too(client: TestClient) -> None:  # noqa: F811
    _onboard(client, OWNER, "family", "Wei Ling")
    group = client.post(
        "/v1/groups",
        json={"senior_name": "Mdm Tan", "relationship": "Daughter"},
        headers=_headers(OWNER),
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["group_id"]
    task_id = _task(client, group_id)["task_id"]
    assert _tick_group(client, group_id, task_id, _today()).status_code == 204
    body = _group_list(client, group_id)
    assert body["person_id"] is None
    assert len(body["tasks"]) == 1 and len(body["ticks"]) == 1


# ── The demo and the safety loop ──────────────────────────────────────────────


def test_the_demo_starts_with_the_sample_tasks_after_a_reset(demo: TestClient) -> None:  # noqa: F811
    first = demo.get("/v1/people/mdm-lim/tasks").json()
    assert [t["title"] for t in first["tasks"]] == [
        "Blood pressure tablet",
        "Vitamin D supplement",
        "Drink a glass of water",
        "Light stretching",
        "Blood pressure tablet",
    ]
    assert {t["repeat"] for t in first["tasks"]} == {"daily"}
    group_id = first["group_id"]
    added = demo.post(
        f"/v1/groups/{group_id}/tasks",
        json={"title": "Call Auntie", "start_date": _today().isoformat(), "time": "19:00"},
    )
    assert added.status_code == 201, added.text
    assert (
        demo.put(
            f"/v1/people/mdm-lim/tasks/task-water/days/{_today().isoformat()}",
            json={"done": True},
        ).status_code
        == 204
    )

    assert demo.post("/v1/demo/reset").status_code == 200
    again = demo.get("/v1/people/mdm-lim/tasks").json()
    assert [t["task_id"] for t in again["tasks"]] == [t["task_id"] for t in first["tasks"]]
    assert again["ticks"] == []


def test_the_safety_loop_never_reads_tasks() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "silverloop"
    readers = [
        source / "policy.py",
        source / "learning.py",
        source / "sql_repository.py",
        *(source / "agent").glob("*.py"),
    ]
    for path in readers:
        text = path.read_text(encoding="utf-8")
        for name in ("family_tasks", "TaskRow", "TaskTickRow"):
            assert name not in text, f"{path.name} mentions {name}"
